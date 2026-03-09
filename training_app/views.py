from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import models
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
import os
import time
import base64

import jwt
import requests
from django.conf import settings

from .models import (
    User, Course, CourseSection, CourseSubSection,
    Package, PackagePurchase,
    Quiz, QuizQuestion, QuizChoice, QuizSubmission, QuizAnswer,
    CourseSchedule, Notification, CourseAnnouncement,
)
from .serializers import (
    RegisterSerializer,
    CourseSerializer,
    CourseCreateSerializer,
    CourseSectionSerializer,
    CourseSubSectionSerializer,
    CustomTokenObtainPairSerializer,
    UserSerializer,
    PackageSerializer,
    PackageCreateSerializer,
    PackagePurchaseSerializer,
    QuizSerializer,
    QuizAdminSerializer,
    QuizCreateSerializer,
    QuizQuestionCreateSerializer,
    QuizSubmissionSerializer,
    QuizSubmissionReviewSerializer,
    TeacherQuizSubmissionRowSerializer,
    CourseScheduleSerializer,
    NotificationSerializer,
    CourseAnnouncementSerializer,
)


def admin_only(user):
    if not user.is_staff:
        raise PermissionDenied("Only admins can perform this action.")


def student_only(user):
    if user.role != "student":
        raise PermissionDenied("Only students can access this resource.")


def teacher_or_admin_only(user):
    if not user.is_staff and user.role != "teacher":
        raise PermissionDenied("Only teachers or admins can perform this action.")


def can_modify_course(user, course):
    if user.is_staff:
        return True
    if user.role == "teacher":
        return course.is_teacher_assigned(user)
    return False


def _mux_auth():
    token_id = getattr(settings, "MUX_TOKEN_ID", "")
    token_secret = getattr(settings, "MUX_TOKEN_SECRET", "")
    if not token_id or not token_secret:
        raise PermissionDenied("Mux is not configured on the backend.")
    return (token_id, token_secret)


def _normalize_mux_private_key(raw_key: str) -> str:
    if not raw_key:
        return ""
    value = raw_key.strip()
    if "BEGIN" in value:
        return value.replace("\\n", "\n")
    try:
        decoded = base64.b64decode(value).decode("utf-8")
        if "BEGIN" in decoded:
            return decoded
    except Exception:
        pass
    return value


def _generate_mux_playback_token(playback_id: str) -> str:
    key_id = getattr(settings, "MUX_SIGNING_KEY_ID", "")
    private_key = _normalize_mux_private_key(getattr(settings, "MUX_SIGNING_PRIVATE_KEY", ""))
    if not key_id or not private_key:
        raise PermissionDenied("Mux signed playback is not configured on the backend.")

    now = int(time.time())
    payload = {
        "sub": playback_id,
        "aud": "v",
        "exp": now + 60 * 60,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": key_id})


def _sync_mux_subsection(subsection: CourseSubSection):
    if not subsection.mux_upload_id:
        return subsection

    upload_res = requests.get(
        f"https://api.mux.com/video/v1/uploads/{subsection.mux_upload_id}",
        auth=_mux_auth(),
        timeout=30,
    )
    upload_res.raise_for_status()
    upload_data = upload_res.json().get("data", {})

    asset_id = upload_data.get("asset_id")
    if asset_id and subsection.mux_asset_id != asset_id:
        subsection.mux_asset_id = asset_id
        subsection.video_status = "processing"
        subsection.save(update_fields=["mux_asset_id", "video_status"])

    if not asset_id:
        if upload_data.get("status") == "cancelled":
            subsection.video_status = "cancelled"
            subsection.save(update_fields=["video_status"])
        return subsection

    asset_res = requests.get(
        f"https://api.mux.com/video/v1/assets/{asset_id}",
        auth=_mux_auth(),
        timeout=30,
    )
    asset_res.raise_for_status()
    asset_data = asset_res.json().get("data", {})

    status_value = asset_data.get("status") or subsection.video_status or "processing"
    playback_ids = asset_data.get("playback_ids") or []
    playback_id = playback_ids[0].get("id") if playback_ids else None

    subsection.mux_asset_id = asset_id
    subsection.mux_playback_id = playback_id or subsection.mux_playback_id
    subsection.video_duration = asset_data.get("duration") or subsection.video_duration
    subsection.video_status = "ready" if playback_id and status_value == "ready" else status_value
    subsection.save(update_fields=["mux_asset_id", "mux_playback_id", "video_duration", "video_status"])
    return subsection


# =====================================================
# PACKAGE ACCESS CHECK (NEW)
# =====================================================
def student_has_course_access(user, course: Course) -> bool:
    """Student can access course content only if they have an active purchase for a published package containing it."""
    return PackagePurchase.objects.filter(
        student=user,
        status="active",
        package__courses=course,
        package__is_published=True,
    ).exists()


def students_with_course_access(course: Course):
    """Return queryset of students that can access this course."""
    # Active purchases for published packages containing the course
    paid_students = User.objects.filter(
        role="student",
        package_purchases__status="active",
        package_purchases__package__is_published=True,
        package_purchases__package__courses=course,
    ).distinct()

    # If course is in a FREE published package, any student can access it.
    is_in_free_pkg = Package.objects.filter(is_published=True, is_free=True, courses=course).exists()
    if is_in_free_pkg:
        return User.objects.filter(role="student").distinct()

    return paid_students


def notify_course_students(course: Course, title: str, message: str, *, schedule=None, url: str = ""):
    """Create in-app notifications for all students with access to the course."""
    students = students_with_course_access(course)
    notifs = [
        Notification(
            user=s,
            title=title,
            message=message,
            course=course,
            schedule=schedule,
            url=url,
        )
        for s in students
    ]
    if notifs:
        Notification.objects.bulk_create(notifs)


# =====================================================
# PUBLIC ENDPOINTS (No authentication required)
# =====================================================

@api_view(["GET"])
@permission_classes([AllowAny])
def featured_courses(request):
    # Storefront visibility is controlled by *packages*, not course publishing.
    # A course appears publicly only if it is included in a published package.
    courses = (
        Course.objects.filter(packages__is_published=True)
        .distinct()
        .order_by("-created_at")[:6]
    )
    serializer = CourseSerializer(courses, many=True, context={"request": request})
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([AllowAny])
def public_courses(request):
    # Public listing = courses that belong to a published package
    courses = Course.objects.filter(packages__is_published=True).distinct().order_by("-created_at")

    exam_target = request.query_params.get("exam_target")
    if exam_target:
        courses = courses.filter(exam_target=exam_target)

    student_class = request.query_params.get("class")
    if student_class:
        courses = courses.filter(student_class=student_class)

    serializer = CourseSerializer(courses, many=True, context={"request": request})
    return Response(serializer.data)


# =====================================================
# PUBLIC PACKAGE ENDPOINTS (NEW)
# =====================================================

@api_view(["GET"])
@permission_classes([AllowAny])
def public_packages(request):
    packages = Package.objects.filter(is_published=True).order_by("-created_at")
    serializer = PackageSerializer(packages, many=True, context={"request": request})
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([AllowAny])
def featured_packages(request):
    packages = Package.objects.filter(is_published=True, featured=True).order_by("-created_at")[:6]
    serializer = PackageSerializer(packages, many=True, context={"request": request})
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([AllowAny])
def package_public_detail(request, pk: int):
    try:
        package = Package.objects.get(pk=pk, is_published=True)
    except Package.DoesNotExist:
        return Response({"detail": "Package not found"}, status=status.HTTP_404_NOT_FOUND)
    serializer = PackageSerializer(package, context={"request": request})
    return Response(serializer.data)


# =====================================================
# AUTH
# =====================================================

@api_view(["POST"])
@permission_classes([AllowAny])
def register_view(request):
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        return Response(
            {
                "message": "Registration successful",
                "user": {"email": user.email, "role": getattr(user, "role", None)},
            },
            status=status.HTTP_201_CREATED,
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    serializer = CustomTokenObtainPairSerializer(data=request.data)
    if serializer.is_valid():
        return Response(serializer.validated_data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# =====================================================
# COURSES (ADMIN ONLY for creation)
# =====================================================

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def course_list_create(request):
    if request.method == "GET":
        if request.user.is_staff:
            courses = Course.objects.all()
        elif request.user.role == "teacher":
            courses = Course.objects.filter(
                Q(assigned_teachers=request.user) | Q(created_by=request.user)
            ).distinct()
        else:
            courses = Course.objects.none()

        serializer = CourseSerializer(courses, many=True, context={"request": request})
        return Response(serializer.data)

    admin_only(request.user)

    serializer = CourseCreateSerializer(data=request.data, context={"request": request})
    if serializer.is_valid():
        course = serializer.save()
        full_serializer = CourseSerializer(course, context={"request": request})
        return Response(full_serializer.data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PUT", "DELETE", "PATCH"])
@permission_classes([IsAuthenticated])
def course_detail(request, pk):
    try:
        course = Course.objects.get(pk=pk)
    except Course.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if request.user.role == "teacher" and not request.user.is_staff:
        if not course.is_teacher_assigned(request.user):
            raise PermissionDenied("You are not assigned to this course.")

    if request.method == "GET":
        serializer = CourseSerializer(course, context={"request": request})
        return Response(serializer.data)

    if not can_modify_course(request.user, course):
        raise PermissionDenied("You don't have permission to modify this course.")

    if request.method == "PUT":
        serializer = CourseSerializer(course, data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    if request.method == "PATCH":
        serializer = CourseSerializer(course, data=request.data, partial=True, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    if request.method == "DELETE":
        admin_only(request.user)
        course.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# =====================================================
# TEACHER ASSIGNMENT ENDPOINTS
# =====================================================

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def teacher_course_list(request):
    if request.user.role != "teacher" and not request.user.is_staff:
        raise PermissionDenied("Only teachers can access this endpoint.")

    courses = Course.objects.filter(
        Q(assigned_teachers=request.user) | Q(created_by=request.user)
    ).distinct()

    serializer = CourseSerializer(courses, many=True, context={"request": request})
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def teacher_course_detail(request, pk):
    if request.user.role != "teacher" and not request.user.is_staff:
        raise PermissionDenied("Only teachers can access this endpoint.")

    try:
        course = Course.objects.get(pk=pk)
        if not request.user.is_staff and not course.is_teacher_assigned(request.user):
            raise PermissionDenied("You are not assigned to this course.")
    except Course.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    serializer = CourseSerializer(course, context={"request": request})
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def teacher_list(request):
    admin_only(request.user)
    teachers = User.objects.filter(role="teacher")
    serializer = UserSerializer(teachers, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def course_teachers(request, pk):
    try:
        course = Course.objects.get(pk=pk)
    except Course.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if not request.user.is_staff and not course.is_teacher_assigned(request.user):
        raise PermissionDenied("You don't have permission to view this information.")

    serializer = UserSerializer(course.assigned_teachers.all(), many=True)
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def assign_teacher(request, pk):
    admin_only(request.user)

    try:
        course = Course.objects.get(pk=pk)
    except Course.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    teacher_id = request.data.get("teacher_id")
    if not teacher_id:
        return Response({"error": "teacher_id is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        teacher = User.objects.get(id=teacher_id, role="teacher")
    except User.DoesNotExist:
        return Response({"error": "Teacher not found"}, status=status.HTTP_404_NOT_FOUND)

    if course.assigned_teachers.filter(id=teacher.id).exists():
        return Response({"message": "Teacher is already assigned to this course"}, status=status.HTTP_200_OK)

    course.assigned_teachers.add(teacher)
    return Response({"message": f"Teacher {teacher.email} assigned to course successfully"}, status=status.HTTP_200_OK)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def remove_teacher(request, pk):
    admin_only(request.user)

    try:
        course = Course.objects.get(pk=pk)
    except Course.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    teacher_id = request.data.get("teacher_id")
    if not teacher_id:
        return Response({"error": "teacher_id is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        teacher = User.objects.get(id=teacher_id, role="teacher")
    except User.DoesNotExist:
        return Response({"error": "Teacher not found"}, status=status.HTTP_404_NOT_FOUND)

    if not course.assigned_teachers.filter(id=teacher.id).exists():
        return Response({"error": "Teacher is not assigned to this course"}, status=status.HTTP_400_BAD_REQUEST)

    course.assigned_teachers.remove(teacher)
    return Response({"message": f"Teacher {teacher.email} removed from course successfully"}, status=status.HTTP_200_OK)


# =====================================================
# SECTIONS (Admin and assigned teachers)
# =====================================================

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def section_list_create(request):
    teacher_or_admin_only(request.user)

    if request.method == "GET":
        if request.user.is_staff:
            sections = CourseSection.objects.all()
        else:
            sections = CourseSection.objects.filter(course__assigned_teachers=request.user).distinct()

        return Response(CourseSectionSerializer(sections, many=True).data)

    data = request.data.copy()
    course_id = data.get("course")

    try:
        course = Course.objects.get(id=course_id)
    except Course.DoesNotExist:
        return Response({"error": "Course not found"}, status=status.HTTP_404_NOT_FOUND)

    if not can_modify_course(request.user, course):
        raise PermissionDenied("You don't have permission to add sections to this course.")

    last_order = (
        CourseSection.objects.filter(course_id=course_id)
        .aggregate(models.Max("order"))["order__max"]
        or 0
    )
    data["order"] = last_order + 1

    serializer = CourseSectionSerializer(data=data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def section_detail(request, pk):
    teacher_or_admin_only(request.user)

    try:
        section = CourseSection.objects.get(pk=pk)
    except CourseSection.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if not can_modify_course(request.user, section.course):
        raise PermissionDenied("You don't have permission to modify this section.")

    if request.method == "GET":
        return Response(CourseSectionSerializer(section).data)

    if request.method == "PUT":
        serializer = CourseSectionSerializer(section, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    section.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# =====================================================
# SUB-SECTIONS (Admin and assigned teachers)
# =====================================================

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def subsection_list_create(request):
    teacher_or_admin_only(request.user)

    if request.method == "GET":
        if request.user.is_staff:
            subs = CourseSubSection.objects.all()
        else:
            subs = CourseSubSection.objects.filter(section__course__assigned_teachers=request.user).distinct()

        return Response(CourseSubSectionSerializer(subs, many=True).data)

    data = request.data.copy()
    section_id = data.get("section")

    try:
        section = CourseSection.objects.get(id=section_id)
    except CourseSection.DoesNotExist:
        return Response({"error": "Section not found"}, status=status.HTTP_404_NOT_FOUND)

    if not can_modify_course(request.user, section.course):
        raise PermissionDenied("You don't have permission to add lectures to this course.")

    last_order = (
        CourseSubSection.objects.filter(section_id=section_id)
        .aggregate(models.Max("order"))["order__max"]
        or 0
    )
    data["order"] = last_order + 1

    serializer = CourseSubSectionSerializer(data=data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def subsection_detail(request, pk):
    teacher_or_admin_only(request.user)

    try:
        sub = CourseSubSection.objects.get(pk=pk)
    except CourseSubSection.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if not can_modify_course(request.user, sub.section.course):
        raise PermissionDenied("You don't have permission to modify this lecture.")

    if request.method == "GET":
        return Response(CourseSubSectionSerializer(sub).data)

    if request.method in ("PUT", "PATCH"):
        # Support replacing uploaded documents via multipart PATCH/PUT
        serializer = CourseSubSectionSerializer(sub, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    sub.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_mux_upload(request, pk):
    teacher_or_admin_only(request.user)

    try:
        subsection = CourseSubSection.objects.get(pk=pk)
    except CourseSubSection.DoesNotExist:
        return Response({"detail": "Subsection not found"}, status=status.HTTP_404_NOT_FOUND)

    if not can_modify_course(request.user, subsection.section.course):
        raise PermissionDenied("You don't have permission to upload video for this lecture.")

    if subsection.content_type != "video":
        return Response({"detail": "Mux uploads are only available for video subsections."}, status=status.HTTP_400_BAD_REQUEST)

    payload = {
        "new_asset_settings": {
            "playback_policy": ["signed"],
            "passthrough": f"subsection:{subsection.id}",
        },
        "cors_origin": request.headers.get("Origin") or "*",
    }

    res = requests.post(
        "https://api.mux.com/video/v1/uploads",
        auth=_mux_auth(),
        json=payload,
        timeout=30,
    )
    try:
        res.raise_for_status()
    except requests.HTTPError:
        return Response(res.json() if res.headers.get("content-type", "").startswith("application/json") else {"detail": "Failed to create Mux upload."}, status=status.HTTP_502_BAD_GATEWAY)

    data = res.json().get("data", {})
    subsection.mux_upload_id = data.get("id")
    subsection.mux_asset_id = None
    subsection.mux_playback_id = None
    subsection.video_status = "upload_created"
    subsection.save(update_fields=["mux_upload_id", "mux_asset_id", "mux_playback_id", "video_status"])

    return Response({
        "upload_id": data.get("id"),
        "upload_url": data.get("url"),
        "status": subsection.video_status,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sync_mux_upload(request, pk):
    teacher_or_admin_only(request.user)

    try:
        subsection = CourseSubSection.objects.get(pk=pk)
    except CourseSubSection.DoesNotExist:
        return Response({"detail": "Subsection not found"}, status=status.HTTP_404_NOT_FOUND)

    if not can_modify_course(request.user, subsection.section.course):
        raise PermissionDenied("You don't have permission to view this upload status.")

    if subsection.content_type != "video" or not subsection.mux_upload_id:
        return Response({"detail": "No Mux upload found for this subsection."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        subsection = _sync_mux_subsection(subsection)
    except requests.RequestException as exc:
        return Response({"detail": f"Failed to sync Mux upload: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

    return Response(CourseSubSectionSerializer(subsection, context={"request": request}).data)


# =====================================================
# STUDENT ENDPOINTS (UPDATED WITH ACCESS CHECKS)
# =====================================================


# =====================================================
# SCHEDULES (Teacher/Admin create; Students view if enrolled)
# =====================================================


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def course_schedule_list_create(request, course_id: int):
    try:
        course = Course.objects.get(pk=course_id)
    except Course.DoesNotExist:
        return Response({"detail": "Course not found"}, status=status.HTTP_404_NOT_FOUND)

    # Students can view schedules if they have access
    if request.method == "GET" and request.user.role == "student":
        if not student_has_course_access(request.user, course):
            return Response({"detail": "You need a package that includes this course."}, status=status.HTTP_403_FORBIDDEN)
        qs = CourseSchedule.objects.filter(course=course).order_by("start_at")
        return Response(CourseScheduleSerializer(qs, many=True).data)

    # Teacher/Admin list & create
    teacher_or_admin_only(request.user)
    if not can_modify_course(request.user, course):
        raise PermissionDenied("You don't have permission to manage schedules for this course.")

    if request.method == "GET":
        qs = CourseSchedule.objects.filter(course=course).order_by("start_at")
        return Response(CourseScheduleSerializer(qs, many=True).data)

    # POST
    serializer = CourseScheduleSerializer(data=request.data)
    if serializer.is_valid():
        sched = serializer.save(course=course, created_by=request.user)

        # Notify students
        notify_course_students(
            course,
            title=f"New class scheduled: {sched.title}",
            message=f"{course.title} • {sched.start_at.strftime('%Y-%m-%d %H:%M')}",
            schedule=sched,
            url=sched.live_link or "",
        )

        return Response(CourseScheduleSerializer(sched).data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PATCH", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def schedule_detail(request, schedule_id: int):
    try:
        sched = CourseSchedule.objects.select_related("course").get(pk=schedule_id)
    except CourseSchedule.DoesNotExist:
        return Response({"detail": "Schedule not found"}, status=status.HTTP_404_NOT_FOUND)

    course = sched.course

    if request.method == "GET" and request.user.role == "student":
        if not student_has_course_access(request.user, course):
            return Response({"detail": "You need a package that includes this course."}, status=status.HTTP_403_FORBIDDEN)
        return Response(CourseScheduleSerializer(sched).data)

    teacher_or_admin_only(request.user)
    if not can_modify_course(request.user, course):
        raise PermissionDenied("You don't have permission to modify this schedule.")

    if request.method in ("PATCH", "PUT"):
        serializer = CourseScheduleSerializer(sched, data=request.data, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            notify_course_students(
                course,
                title=f"Schedule updated: {updated.title}",
                message=f"{course.title} • {updated.start_at.strftime('%Y-%m-%d %H:%M')}",
                schedule=updated,
                url=updated.live_link or "",
            )
            return Response(CourseScheduleSerializer(updated).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    if request.method == "DELETE":
        # Notify cancellation
        notify_course_students(
            course,
            title=f"Class cancelled: {sched.title}",
            message=f"{course.title} • {sched.start_at.strftime('%Y-%m-%d %H:%M')}",
            schedule=None,
            url="",
        )
        sched.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    return Response(CourseScheduleSerializer(sched).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_schedules(request):
    """All schedules for courses the student can access."""
    student_only(request.user)

    # Courses student can access
    purchased_course_ids = Course.objects.filter(
        packages__purchases__student=request.user,
        packages__purchases__status="active",
        packages__is_published=True,
    ).values_list("id", flat=True)

    free_course_ids = Course.objects.filter(
        packages__is_published=True,
        packages__is_free=True,
    ).values_list("id", flat=True)

    course_ids = list(set(list(purchased_course_ids) + list(free_course_ids)))
    qs = CourseSchedule.objects.filter(course_id__in=course_ids).select_related("course").order_by("start_at")
    return Response(CourseScheduleSerializer(qs, many=True).data)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def student_notifications(request):
    """List notifications and mark read."""
    student_only(request.user)

    if request.method == "GET":
        qs = Notification.objects.filter(user=request.user).order_by("-created_at")
        return Response(NotificationSerializer(qs, many=True).data)

    # PATCH: mark as read
    notif_id = request.data.get("id")
    if notif_id:
        Notification.objects.filter(user=request.user, id=notif_id).update(is_read=True)
    else:
        # mark all
        Notification.objects.filter(user=request.user).update(is_read=True)

    return Response({"ok": True})


# =====================================================
# ANNOUNCEMENTS (Teacher/Admin post; Students view if enrolled)
# =====================================================


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def course_announcement_list_create(request, course_id: int):
    try:
        course = Course.objects.get(pk=course_id)
    except Course.DoesNotExist:
        return Response({"detail": "Course not found"}, status=status.HTTP_404_NOT_FOUND)

    # Students can view announcements if they have access
    if request.method == "GET" and request.user.role == "student":
        if not student_has_course_access(request.user, course):
            return Response({"detail": "You need a package that includes this course."}, status=status.HTTP_403_FORBIDDEN)
        qs = CourseAnnouncement.objects.filter(course=course).order_by("-created_at")
        return Response(CourseAnnouncementSerializer(qs, many=True).data)

    # Teacher/Admin list & create
    teacher_or_admin_only(request.user)
    if not can_modify_course(request.user, course):
        raise PermissionDenied("You don't have permission to manage announcements for this course.")

    if request.method == "GET":
        qs = CourseAnnouncement.objects.filter(course=course).order_by("-created_at")
        return Response(CourseAnnouncementSerializer(qs, many=True).data)

    serializer = CourseAnnouncementSerializer(data=request.data)
    if serializer.is_valid():
        ann = serializer.save(course=course, created_by=request.user)

        # Notify students
        notify_course_students(
            course,
            title=f"New announcement: {ann.title}",
            message=(ann.message or "")[:400],
            schedule=None,
            url=ann.link or "",
        )

        return Response(CourseAnnouncementSerializer(ann).data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PATCH", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def announcement_detail(request, announcement_id: int):
    try:
        ann = CourseAnnouncement.objects.select_related("course").get(pk=announcement_id)
    except CourseAnnouncement.DoesNotExist:
        return Response({"detail": "Announcement not found"}, status=status.HTTP_404_NOT_FOUND)

    course = ann.course

    if request.method == "GET" and request.user.role == "student":
        if not student_has_course_access(request.user, course):
            return Response({"detail": "You need a package that includes this course."}, status=status.HTTP_403_FORBIDDEN)
        return Response(CourseAnnouncementSerializer(ann).data)

    teacher_or_admin_only(request.user)
    if not can_modify_course(request.user, course):
        raise PermissionDenied("You don't have permission to modify this announcement.")

    if request.method in ("PATCH", "PUT"):
        serializer = CourseAnnouncementSerializer(ann, data=request.data, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            notify_course_students(
                course,
                title=f"Announcement updated: {updated.title}",
                message=(updated.message or "")[:400],
                schedule=None,
                url=updated.link or "",
            )
            return Response(CourseAnnouncementSerializer(updated).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    if request.method == "DELETE":
        ann.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    return Response(CourseAnnouncementSerializer(ann).data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_course_list(request):
    student_only(request.user)

    # courses in ACTIVE purchases (published packages only)
    purchased_course_ids = Course.objects.filter(
        packages__purchases__student=request.user,
        packages__purchases__status="active",
        packages__is_published=True,
    ).values_list("id", flat=True)

    # courses inside FREE published packages
    free_package_course_ids = Course.objects.filter(
        packages__is_published=True,
        packages__is_free=True,
    ).values_list("id", flat=True)

    courses = Course.objects.filter(
        is_published=True,
        id__in=list(purchased_course_ids) + list(free_package_course_ids),
    ).distinct()

    serializer = CourseSerializer(courses, many=True, context={"request": request})
    return Response(serializer.data)



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_course_detail(request, pk):
    student_only(request.user)

    try:
        course = Course.objects.get(pk=pk, is_published=True)
    except Course.DoesNotExist:
        return Response({"detail": "Course not found"}, status=status.HTTP_404_NOT_FOUND)

    # ✅ GATE CONTENT HERE
    if not student_has_course_access(request.user, course):
        return Response(
            {"detail": "You need to purchase a package that includes this course to access it."},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = CourseSerializer(course, context={"request": request})
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_subsection_detail(request, pk):
    student_only(request.user)

    try:
        subsection = CourseSubSection.objects.get(pk=pk)
    except CourseSubSection.DoesNotExist:
        return Response({"detail": "Subsection not found"}, status=status.HTTP_404_NOT_FOUND)

    course = subsection.section.course
    if not course.is_published:
        return Response({"detail": "Course not available"}, status=status.HTTP_404_NOT_FOUND)

    # ✅ GATE LECTURE HERE
    if not student_has_course_access(request.user, course):
        return Response(
            {"detail": "You need to purchase a package that includes this course to access it."},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = CourseSubSectionSerializer(subsection, context={"request": request})
    return Response(serializer.data)




# =====================================================
# QUIZ ENDPOINTS
# =====================================================

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def course_quiz_list_create(request, course_id: int):
    """Teachers/Admin create/list quizzes for a course they can modify.
    Students list quizzes for a course they have access to (via a purchased published package)."""

    # -----------------------------
    # Resolve course with role-aware rules
    # -----------------------------
    if request.method == "GET" and request.user.role == "student":
        try:
            course = Course.objects.get(pk=course_id)
        except Course.DoesNotExist:
            return Response({"detail": "Course not found"}, status=status.HTTP_404_NOT_FOUND)

        if not student_has_course_access(request.user, course):
            return Response({"detail": "You need a package that includes this course."}, status=status.HTTP_403_FORBIDDEN)

        # Quizzes are immediately visible; rules (due/time/attempts) control access.
        quizzes = Quiz.objects.filter(course=course).order_by("-created_at")
        return Response(QuizSerializer(quizzes, many=True, context={"request": request}).data)

    # Teachers/Admin can work with drafts too
    try:
        course = Course.objects.get(pk=course_id)
    except Course.DoesNotExist:
        return Response({"detail": "Course not found"}, status=status.HTTP_404_NOT_FOUND)

    # -----------------------------
    # Teacher/Admin list all quizzes
    # -----------------------------
    if request.method == "GET":
        teacher_or_admin_only(request.user)
        if not can_modify_course(request.user, course):
            raise PermissionDenied("You don't have permission to view quizzes for this course.")

        quizzes = Quiz.objects.filter(course=course).order_by("-created_at")
        return Response(QuizAdminSerializer(quizzes, many=True, context={"request": request}).data)

    # -----------------------------
    # Teacher/Admin create quiz
    # -----------------------------
    teacher_or_admin_only(request.user)
    if not can_modify_course(request.user, course):
        raise PermissionDenied("You don't have permission to create quizzes for this course.")

    serializer = QuizCreateSerializer(data=request.data)
    if serializer.is_valid():
        quiz = serializer.save(course=course, created_by=request.user)
        return Response(QuizAdminSerializer(quiz, context={"request": request}).data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def quiz_detail(request, quiz_id: int):
    try:
        quiz = Quiz.objects.select_related("course").get(pk=quiz_id)
    except Quiz.DoesNotExist:
        return Response({"detail": "Quiz not found"}, status=status.HTTP_404_NOT_FOUND)

    # STUDENT GET (take quiz): published + course access; return without correct answers
    if request.method == "GET" and request.user.role == "student":
        # Course visibility is controlled by package purchase; quizzes are available once created.
        if not student_has_course_access(request.user, quiz.course):
            return Response({"detail": "You need a package that includes this course."}, status=status.HTTP_403_FORBIDDEN)
        return Response(QuizSerializer(quiz, context={"request": request}).data)

    teacher_or_admin_only(request.user)
    if not can_modify_course(request.user, quiz.course):
        raise PermissionDenied("You don't have permission to modify this quiz.")

    if request.method == "GET":
        return Response(QuizAdminSerializer(quiz, context={"request": request}).data)

    if request.method == "PATCH":
        serializer = QuizCreateSerializer(quiz, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(QuizAdminSerializer(quiz, context={"request": request}).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    quiz.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def quiz_add_question(request, quiz_id: int):
    teacher_or_admin_only(request.user)
    try:
        quiz = Quiz.objects.select_related("course").get(pk=quiz_id)
    except Quiz.DoesNotExist:
        return Response({"detail": "Quiz not found"}, status=status.HTTP_404_NOT_FOUND)

    if not can_modify_course(request.user, quiz.course):
        raise PermissionDenied("You don't have permission to add questions to this quiz.")

    serializer = QuizQuestionCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    choices_data = serializer.validated_data.pop("choices")
    question = QuizQuestion.objects.create(quiz=quiz, **serializer.validated_data)

    # create choices
    for c in choices_data:
        QuizChoice.objects.create(
            question=question,
            text=c.get("text"),
            is_correct=bool(c.get("is_correct")),
        )

    return Response(QuizAdminSerializer(quiz, context={"request": request}).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def quiz_submit(request, quiz_id: int):
    student_only(request.user)

    try:
        quiz = Quiz.objects.select_related("course").get(pk=quiz_id, is_published=True, course__is_published=True)
    except Quiz.DoesNotExist:
        return Response({"detail": "Quiz not found"}, status=status.HTTP_404_NOT_FOUND)

    if not student_has_course_access(request.user, quiz.course):
        return Response({"detail": "You need a package that includes this course."}, status=status.HTTP_403_FORBIDDEN)

    # PDF quiz flow: student uploads a file for teacher grading.
    if quiz.quiz_type == "pdf":
        submission_file = request.data.get("submission_file")
        if not submission_file:
            return Response({"detail": "Please upload your answer PDF/file."}, status=status.HTTP_400_BAD_REQUEST)

        if quiz.due_at and timezone.now() > quiz.due_at:
            return Response({"detail": "Quiz is past due."}, status=status.HTTP_403_FORBIDDEN)

        submitted_count = QuizSubmission.objects.filter(quiz=quiz, student=request.user, status="submitted").count()
        if submitted_count >= 1:
            return Response({"detail": "You have already submitted this PDF quiz."}, status=status.HTTP_403_FORBIDDEN)

        submission = QuizSubmission.objects.create(
            quiz=quiz,
            student=request.user,
            total=100,
            score=0,
            status="submitted",
            attempt_number=1,
            submission_file=submission_file,
            submitted_at=timezone.now(),
            time_taken_seconds=0,
        )
        return Response({
            "submission": QuizSubmissionSerializer(submission, context={"request": request}).data,
            "score": submission.score,
            "total": submission.total,
            "percent": 0,
            "manual_grading_pending": True,
        }, status=status.HTTP_201_CREATED)

    attempt_id = request.data.get("attempt_id")
    answers = request.data.get("answers")
    if not isinstance(answers, dict):
        return Response({"detail": "answers must be an object mapping question_id -> choice_id"}, status=status.HTTP_400_BAD_REQUEST)

    # Backward compatibility: if attempt_id is not provided, create an attempt on-the-fly.
    if not attempt_id:
        submitted_count = QuizSubmission.objects.filter(quiz=quiz, student=request.user, status="submitted").count()

        if quiz.due_at and timezone.now() > quiz.due_at:
            return Response({"detail": "Quiz is past due."}, status=status.HTTP_403_FORBIDDEN)

        if not quiz.allow_retakes and submitted_count >= 1:
            return Response({"detail": "Retakes are not allowed for this quiz."}, status=status.HTTP_403_FORBIDDEN)

        if quiz.allow_retakes and quiz.max_attempts != 0 and submitted_count >= quiz.max_attempts:
            return Response({"detail": "No attempts remaining."}, status=status.HTTP_403_FORBIDDEN)

        total = quiz.questions.count()
        attempt_number = submitted_count + 1
        submission = QuizSubmission.objects.create(
            quiz=quiz,
            student=request.user,
            total=total,
            score=0,
            status="in_progress",
            attempt_number=attempt_number,
        )
    else:
        try:
            submission = QuizSubmission.objects.select_related("quiz").get(
                pk=attempt_id,
                quiz=quiz,
                student=request.user,
            )
        except QuizSubmission.DoesNotExist:
            return Response({"detail": "Attempt not found"}, status=status.HTTP_404_NOT_FOUND)

    if submission.status != "in_progress":
        return Response({"detail": "Attempt is not in progress"}, status=status.HTTP_400_BAD_REQUEST)

    # Due date enforcement
    if quiz.due_at and timezone.now() > quiz.due_at:
        submission.status = "expired"
        submission.submitted_at = timezone.now()
        submission.time_taken_seconds = int((submission.submitted_at - submission.started_at).total_seconds())
        submission.save(update_fields=["status", "submitted_at", "time_taken_seconds"])
        return Response({"detail": "Quiz is past due."}, status=status.HTTP_403_FORBIDDEN)

    # Time limit enforcement
    if quiz.time_limit_minutes:
        expires_at = submission.started_at + timedelta(minutes=quiz.time_limit_minutes)
        if timezone.now() > expires_at:
            submission.status = "expired"
            submission.submitted_at = timezone.now()
            submission.time_taken_seconds = int((submission.submitted_at - submission.started_at).total_seconds())
            submission.save(update_fields=["status", "submitted_at", "time_taken_seconds"])
            return Response({"detail": "Time limit exceeded."}, status=status.HTTP_403_FORBIDDEN)

    # Clear any prior answers for this attempt (idempotent submit retries)
    submission.answers.all().delete()

    questions = list(quiz.questions.prefetch_related("choices").all())
    total = len(questions)
    score = 0

    submission.total = total
    submission.score = 0
    submission.save(update_fields=["total", "score"])

    per_question = []
    for q in questions:
        selected_choice_id = answers.get(str(q.id)) or answers.get(q.id)
        selected_choice = None
        if selected_choice_id is not None:
            selected_choice = QuizChoice.objects.filter(id=selected_choice_id, question=q).first()

        correct_choice = next((c for c in q.choices.all() if c.is_correct), None)
        is_correct = selected_choice is not None and correct_choice is not None and selected_choice.id == correct_choice.id
        if is_correct:
            score += 1

        QuizAnswer.objects.create(
            submission=submission,
            question=q,
            selected_choice=selected_choice,
            is_correct=is_correct,
        )
        per_question.append({
            "question_id": q.id,
            "selected_choice_id": selected_choice.id if selected_choice else None,
            "correct_choice_id": correct_choice.id if correct_choice else None,
            "is_correct": is_correct,
        })

    submission.score = score
    submission.total = total
    submission.status = "submitted"
    submission.submitted_at = timezone.now()
    submission.time_taken_seconds = int((submission.submitted_at - submission.started_at).total_seconds())
    submission.save(update_fields=["score", "total", "status", "submitted_at", "time_taken_seconds"])

    percent = round((score / total) * 100, 2) if total > 0 else 0.0

    return Response({
        "submission": QuizSubmissionSerializer(submission, context={"request": request}).data,
        "score": score,
        "total": total,
        "percent": percent,
        "results": per_question,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_quiz_status(request, quiz_id: int):
    """Return scheduling + attempts for the current student."""
    student_only(request.user)

    try:
        quiz = Quiz.objects.select_related("course").get(pk=quiz_id, is_published=True, course__is_published=True)
    except Quiz.DoesNotExist:
        return Response({"detail": "Quiz not found"}, status=status.HTTP_404_NOT_FOUND)

    if not student_has_course_access(request.user, quiz.course):
        return Response({"detail": "You need a package that includes this course."}, status=status.HTTP_403_FORBIDDEN)

    now = timezone.now()
    past_due = bool(quiz.due_at and now > quiz.due_at)

    submitted_count = QuizSubmission.objects.filter(quiz=quiz, student=request.user, status="submitted").count()
    unlimited = bool(quiz.allow_retakes and quiz.max_attempts == 0)
    max_attempts = 1 if not quiz.allow_retakes else int(quiz.max_attempts or 0)

    attempts_left = None
    if not unlimited:
        attempts_left = max(0, max_attempts - submitted_count)

    can_start = (not past_due) and (unlimited or (attempts_left and attempts_left > 0))

    in_progress = QuizSubmission.objects.filter(quiz=quiz, student=request.user, status="in_progress").order_by("-started_at").first()
    expires_at = None
    if in_progress and quiz.time_limit_minutes:
        expires_at = in_progress.started_at + timedelta(minutes=quiz.time_limit_minutes)

    return Response({
        "quiz_id": quiz.id,
        "quiz_type": quiz.quiz_type,
        "question_pdf": request.build_absolute_uri(quiz.question_pdf.url) if quiz.question_pdf else None,
        "due_at": quiz.due_at,
        "time_limit_minutes": quiz.time_limit_minutes,
        "max_attempts": quiz.max_attempts,
        "allow_retakes": quiz.allow_retakes,
        "attempts_used": submitted_count,
        "attempts_left": attempts_left,
        "unlimited_attempts": unlimited,
        "past_due": past_due,
        "can_start": can_start,
        "in_progress_attempt_id": in_progress.id if in_progress else None,
        "started_at": in_progress.started_at if in_progress else None,
        "expires_at": expires_at,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def student_quiz_start(request, quiz_id: int):
    """Create/reuse an in-progress attempt and return quiz data."""
    student_only(request.user)

    try:
        quiz = Quiz.objects.select_related("course").get(pk=quiz_id, is_published=True, course__is_published=True)
    except Quiz.DoesNotExist:
        return Response({"detail": "Quiz not found"}, status=status.HTTP_404_NOT_FOUND)

    if not student_has_course_access(request.user, quiz.course):
        return Response({"detail": "You need a package that includes this course."}, status=status.HTTP_403_FORBIDDEN)

    now = timezone.now()
    if quiz.due_at and now > quiz.due_at:
        return Response({"detail": "Quiz is past due."}, status=status.HTTP_403_FORBIDDEN)

    if quiz.quiz_type == "pdf":
        existing_submitted = QuizSubmission.objects.filter(quiz=quiz, student=request.user, status="submitted").order_by("-created_at").first()
        if existing_submitted:
            return Response({
                "attempt_id": existing_submitted.id,
                "started_at": existing_submitted.started_at,
                "expires_at": None,
                "quiz": QuizSerializer(quiz, context={"request": request}).data,
                "already_submitted": True,
                "submission": QuizSubmissionSerializer(existing_submitted, context={"request": request}).data,
            })
        return Response({
            "attempt_id": None,
            "started_at": None,
            "expires_at": None,
            "quiz": QuizSerializer(quiz, context={"request": request}).data,
        }, status=status.HTTP_200_OK)

    existing = QuizSubmission.objects.filter(quiz=quiz, student=request.user, status="in_progress").order_by("-started_at").first()
    if existing:
        expires_at = None
        if quiz.time_limit_minutes:
            expires_at = existing.started_at + timedelta(minutes=quiz.time_limit_minutes)
        return Response({
            "attempt_id": existing.id,
            "started_at": existing.started_at,
            "expires_at": expires_at,
            "quiz": QuizSerializer(quiz, context={"request": request}).data,
        })

    submitted_count = QuizSubmission.objects.filter(quiz=quiz, student=request.user, status="submitted").count()

    if not quiz.allow_retakes and submitted_count >= 1:
        return Response({"detail": "Retakes are not allowed for this quiz."}, status=status.HTTP_403_FORBIDDEN)

    if quiz.allow_retakes and quiz.max_attempts != 0 and submitted_count >= quiz.max_attempts:
        return Response({"detail": "No attempts remaining."}, status=status.HTTP_403_FORBIDDEN)

    total = quiz.questions.count()
    attempt_number = submitted_count + 1

    submission = QuizSubmission.objects.create(
        quiz=quiz,
        student=request.user,
        total=total,
        score=0,
        status="in_progress",
        attempt_number=attempt_number,
    )

    expires_at = None
    if quiz.time_limit_minutes:
        expires_at = submission.started_at + timedelta(minutes=quiz.time_limit_minutes)

    return Response({
        "attempt_id": submission.id,
        "started_at": submission.started_at,
        "expires_at": expires_at,
        "quiz": QuizSerializer(quiz, context={"request": request}).data,
    }, status=status.HTTP_201_CREATED)



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_quiz_submissions(request):
    student_only(request.user)
    subs = QuizSubmission.objects.select_related("quiz", "quiz__course").filter(student=request.user).order_by("-created_at")
    return Response(QuizSubmissionSerializer(subs, many=True, context={"request": request}).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_quiz_submission_detail(request, submission_id: int):
    """Detailed review view for a specific quiz attempt/submission."""
    student_only(request.user)
    try:
        submission = (
            QuizSubmission.objects
            .select_related("quiz", "quiz__course")
            .get(pk=submission_id, student=request.user)
        )
    except QuizSubmission.DoesNotExist:
        return Response({"detail": "Submission not found"}, status=status.HTTP_404_NOT_FOUND)

    # Load answers in one query.
    answers = QuizAnswer.objects.select_related("selected_choice", "question").filter(submission=submission)
    answers_by_question = {a.question_id: a for a in answers}

    serializer = QuizSubmissionReviewSerializer(
        submission,
        context={"request": request, "answers_by_question": answers_by_question},
    )
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def teacher_quiz_submissions(request, quiz_id: int):
    teacher_or_admin_only(request.user)
    try:
        quiz = Quiz.objects.select_related("course").get(pk=quiz_id)
    except Quiz.DoesNotExist:
        return Response({"detail": "Quiz not found"}, status=status.HTTP_404_NOT_FOUND)

    if not can_modify_course(request.user, quiz.course):
        raise PermissionDenied("You don't have permission to view submissions for this quiz.")

    subs = QuizSubmission.objects.select_related("student").filter(quiz=quiz).order_by("-created_at")[:2000]
    return Response(TeacherQuizSubmissionRowSerializer(subs, many=True, context={"request": request}).data)



@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def teacher_grade_quiz_submission(request, submission_id: int):
    teacher_or_admin_only(request.user)
    try:
        submission = QuizSubmission.objects.select_related("quiz", "quiz__course").get(pk=submission_id)
    except QuizSubmission.DoesNotExist:
        return Response({"detail": "Submission not found"}, status=status.HTTP_404_NOT_FOUND)

    if not can_modify_course(request.user, submission.quiz.course):
        raise PermissionDenied("You don't have permission to grade this submission.")

    score = request.data.get("score")
    total = request.data.get("total") or submission.total or 100
    feedback = request.data.get("feedback", submission.feedback)

    try:
        score = int(score)
        total = int(total)
    except (TypeError, ValueError):
        return Response({"detail": "score and total must be numbers."}, status=status.HTTP_400_BAD_REQUEST)

    if total <= 0 or score < 0 or score > total:
        return Response({"detail": "Enter a valid score between 0 and total."}, status=status.HTTP_400_BAD_REQUEST)

    submission.score = score
    submission.total = total
    submission.feedback = feedback or ""
    submission.graded_at = timezone.now()
    submission.graded_by = request.user
    if not submission.submitted_at:
        submission.submitted_at = timezone.now()
    if submission.status == "in_progress":
        submission.status = "submitted"
    submission.save(update_fields=["score", "total", "feedback", "graded_at", "graded_by", "submitted_at", "status"])

    return Response(TeacherQuizSubmissionRowSerializer(submission, context={"request": request}).data)

# =====================================================
# ADMIN PACKAGE CRUD (NEW)
# =====================================================

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def package_list_create(request):
    if request.method == "GET":
        admin_only(request.user)
        packages = Package.objects.all().order_by("-created_at")
        serializer = PackageSerializer(packages, many=True, context={"request": request})
        return Response(serializer.data)

    admin_only(request.user)
    payload = request.data.copy()
    if hasattr(request.data, "getlist"):
        course_ids = request.data.getlist("course_ids")
        if course_ids:
            payload.setlist("course_ids", course_ids)
    serializer = PackageCreateSerializer(data=payload, context={"request": request})
    if serializer.is_valid():
        package = serializer.save()
        return Response(PackageSerializer(package, context={"request": request}).data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def package_detail(request, pk: int):
    admin_only(request.user)
    try:
        package = Package.objects.get(pk=pk)
    except Package.DoesNotExist:
        return Response({"detail": "Package not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        return Response(PackageSerializer(package, context={"request": request}).data)

    if request.method == "PATCH":
        # support toggling featured/published, pricing, course updates if needed later
        payload = request.data.copy()
        if hasattr(request.data, "getlist"):
            course_ids = request.data.getlist("course_ids")
            if course_ids:
                payload.setlist("course_ids", course_ids)
        serializer = PackageCreateSerializer(package, data=payload, partial=True, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response(PackageSerializer(package, context={"request": request}).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    package.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# =====================================================
# STUDENT PACKAGE PURCHASE (NEW)
# =====================================================

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def purchase_package(request, pk: int):
    student_only(request.user)

    try:
        package = Package.objects.get(pk=pk, is_published=True)
    except Package.DoesNotExist:
        return Response({"detail": "Package not found"}, status=status.HTTP_404_NOT_FOUND)

    purchase, created = PackagePurchase.objects.get_or_create(
        student=request.user,
        package=package,
        defaults={"status": "active"},
    )

    # For v1 we treat it as instant purchase success
    return Response(
        {
            "message": "Package unlocked" if created else "Package already owned",
            "purchase": PackagePurchaseSerializer(purchase, context={"request": request}).data,
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_purchases(request):
    student_only(request.user)
    purchases = PackagePurchase.objects.filter(student=request.user, status="active").order_by("-created_at")
    serializer = PackagePurchaseSerializer(purchases, many=True, context={"request": request})
    return Response(serializer.data)
