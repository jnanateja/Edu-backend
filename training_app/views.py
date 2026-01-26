from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.decorators import api_view, permission_classes, parser_classes
from django.db import models



from .models import Course, CourseSection, CourseSubSection
from .serializers import (
    RegisterSerializer,
    CourseSerializer,
    CourseSectionSerializer,
    CourseSubSectionSerializer,
)

from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import CustomTokenObtainPairSerializer

# =====================================================
# REGISTER
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
                    "role": user.role,
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
        return Response(serializer.validated_data, status=status.HTTP_200_OK)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

# =====================================================
# PERMISSION CHECK
# =====================================================
def teacher_only(user):
    if user.role != "teacher":
        raise PermissionDenied("Only teachers can perform this action.")


# =====================================================
# COURSES
# =====================================================
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def course_list_create(request):
    teacher_only(request.user)

    if request.method == "GET":
        courses = Course.objects.filter(teacher=request.user)
        serializer = CourseSerializer(courses, many=True)
        return Response(serializer.data)

    serializer = CourseSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save(teacher=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def course_detail(request, pk):
    teacher_only(request.user)

    try:
        course = Course.objects.get(pk=pk, teacher=request.user)
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
# SECTIONS
# =====================================================
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def section_list_create(request):
    teacher_only(request.user)

    if request.method == "GET":
        sections = CourseSection.objects.filter(
            course__teacher=request.user
        )
        return Response(
            CourseSectionSerializer(sections, many=True).data
        )

    # 🔥 AUTO-ORDER LOGIC
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
        course = serializer.validated_data["course"]

        if course.teacher != request.user:
            raise PermissionDenied("You do not own this course.")

        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def section_detail(request, pk):
    teacher_only(request.user)

    try:
        section = CourseSection.objects.get(
            pk=pk, course__teacher=request.user
        )
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
# SUB-SECTIONS
# =====================================================
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def subsection_list_create(request):

    teacher_only(request.user)

    if request.method == "POST":
        data = request.data.copy()
        section_id = data.get("section")

        # 🔥 AUTO-ORDER LOGIC
        last_order = (
            CourseSubSection.objects
            .filter(section_id=section_id)
            .aggregate(models.Max("order"))["order__max"]
            or 0
        )

        data["order"] = last_order + 1

        serializer = CourseSubSectionSerializer(data=data)
        if serializer.is_valid():
            section = serializer.validated_data["section"]

            if section.course.teacher != request.user:
                raise PermissionDenied("You do not own this course.")

            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def subsection_detail(request, pk):
    teacher_only(request.user)

    try:
        sub = CourseSubSection.objects.get(
            pk=pk, section__course__teacher=request.user
        )
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
