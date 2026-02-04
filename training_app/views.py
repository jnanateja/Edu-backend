from rest_framework.decorators import (
    api_view,
    permission_classes,
    parser_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import models

from .models import Course, CourseSection, CourseSubSection
from .serializers import (
    RegisterSerializer,
    CourseSerializer,
    CourseSectionSerializer,
    CourseSubSectionSerializer,
    CustomTokenObtainPairSerializer,
)

def admin_only(user):
    if not user.is_staff:
        raise PermissionDenied("Only admins can perform this action.")


def student_only(user):
    if user.role != "student":
        raise PermissionDenied("Only students can access this resource.")

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
                "user": {
                    "email": user.email,
                    "role": getattr(user, "role", None),
                },
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


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def course_list_create(request):
    admin_only(request.user)

    if request.method == "GET":
        courses = Course.objects.all()
        return Response(CourseSerializer(courses, many=True).data)

    serializer = CourseSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save(teacher=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def course_detail(request, pk):
    admin_only(request.user)

    try:
        course = Course.objects.get(pk=pk)
    except Course.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        return Response(CourseSerializer(course).data)

    if request.method == "PUT":
        serializer = CourseSerializer(course, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    course.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# =====================================================
# SECTIONS (ADMIN ONLY)
# =====================================================
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def section_list_create(request):
    admin_only(request.user)

    if request.method == "GET":
        sections = CourseSection.objects.all()
        return Response(
            CourseSectionSerializer(sections, many=True).data
        )

    data = request.data.copy()
    course_id = data.get("course")

    last_order = (
        CourseSection.objects
        .filter(course_id=course_id)
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
    admin_only(request.user)

    try:
        section = CourseSection.objects.get(pk=pk)
    except CourseSection.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

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
# SUB-SECTIONS (ADMIN ONLY)
# =====================================================
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def subsection_list_create(request):
    admin_only(request.user)

    if request.method == "GET":
        subs = CourseSubSection.objects.all()
        return Response(
            CourseSubSectionSerializer(subs, many=True).data
        )

    data = request.data.copy()
    section_id = data.get("section")

    last_order = (
        CourseSubSection.objects
        .filter(section_id=section_id)
        .aggregate(models.Max("order"))["order__max"]
        or 0
    )

    data["order"] = last_order + 1

    serializer = CourseSubSectionSerializer(data=data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def subsection_detail(request, pk):
    admin_only(request.user)

    try:
        sub = CourseSubSection.objects.get(pk=pk)
    except CourseSubSection.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        return Response(CourseSubSectionSerializer(sub).data)

    if request.method == "PUT":
        serializer = CourseSubSectionSerializer(sub, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    sub.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_course_list(request):
    student_only(request.user)

    courses = Course.objects.filter(is_published=True)
    serializer = CourseSerializer(courses, many=True)
    return Response(serializer.data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_course_detail(request, pk):
    student_only(request.user)

    try:
        course = Course.objects.get(pk=pk, is_published=True)
    except Course.DoesNotExist:
        return Response(
            {"detail": "Course not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = CourseSerializer(course)
    return Response(serializer.data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_subsection_detail(request, pk):
    student_only(request.user)

    try:
        subsection = CourseSubSection.objects.get(pk=pk)
    except CourseSubSection.DoesNotExist:
        return Response(
            {"detail": "Subsection not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = CourseSubSectionSerializer(subsection)
    return Response(serializer.data)
