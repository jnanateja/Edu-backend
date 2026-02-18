from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import models
from django.db.models import Q

from .models import (
    User, Course, CourseSection, CourseSubSection,
    Package, PackagePurchase,
    Quiz, QuizQuestion, QuizChoice, QuizSubmission, QuizAnswer
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
    TeacherQuizSubmissionRowSerializer,
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


# =====================================================
# PUBLIC ENDPOINTS (No authentication required)
# =====================================================

@api_view(["GET"])
@permission_classes([AllowAny])
def featured_courses(request):
    courses = Course.objects.filter(is_published=True).order_by("-created_at")[:6]
    serializer = CourseSerializer(courses, many=True, context={"request": request})
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([AllowAny])
def public_courses(request):
    courses = Course.objects.filter(is_published=True).order_by("-created_at")

    exam_target = request.query_params.get("exam_target")
    if exam_target:
        courses = courses.filter(exam_target=exam_target)

    student_class = request.query_params.get("class")
    if student_class:
        courses = courses.filter(student_class=student_class)
        courses = courses.filter(is_free=False)

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


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
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

    if request.method == "PUT":
        serializer = CourseSubSectionSerializer(sub, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    sub.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# =====================================================
# STUDENT ENDPOINTS (UPDATED WITH ACCESS CHECKS)
# =====================================================

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

    serializer = CourseSubSectionSerializer(subsection)
    return Response(serializer.data)




# =====================================================
# QUIZ ENDPOINTS
# =====================================================

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def course_quiz_list_create(request, course_id: int):
    """Teachers/Admin create quizzes for a course they can modify. Students list published quizzes for an unlocked course."""
    try:
        course = Course.objects.get(pk=course_id, is_published=True)
    except Course.DoesNotExist:
        return Response({"detail": "Course not found"}, status=status.HTTP_404_NOT_FOUND)

    # STUDENT: list published quizzes only, requires access to course via package
    if request.method == "GET" and request.user.role == "student":
        if not student_has_course_access(request.user, course):
            return Response({"detail": "You need a package that includes this course."}, status=status.HTTP_403_FORBIDDEN)
        quizzes = Quiz.objects.filter(course=course, is_published=True).order_by("-created_at")
        return Response(QuizSerializer(quizzes, many=True, context={"request": request}).data)

    # TEACHER/ADMIN: list all quizzes for course if can modify course
    if request.method == "GET":
        teacher_or_admin_only(request.user)
        if not can_modify_course(request.user, course):
            raise PermissionDenied("You don't have permission to view quizzes for this course.")
        quizzes = Quiz.objects.filter(course=course).order_by("-created_at")
        return Response(QuizAdminSerializer(quizzes, many=True, context={"request": request}).data)

    # CREATE
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
def quiz_detail(request, quiz_id: int):
    try:
        quiz = Quiz.objects.select_related("course").get(pk=quiz_id)
    except Quiz.DoesNotExist:
        return Response({"detail": "Quiz not found"}, status=status.HTTP_404_NOT_FOUND)

    # STUDENT GET (take quiz): published + course access; return without correct answers
    if request.method == "GET" and request.user.role == "student":
        if not quiz.is_published or not quiz.course.is_published:
            return Response({"detail": "Quiz not available"}, status=status.HTTP_404_NOT_FOUND)
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
def quiz_submit(request, quiz_id: int):
    student_only(request.user)

    try:
        quiz = Quiz.objects.select_related("course").get(pk=quiz_id, is_published=True, course__is_published=True)
    except Quiz.DoesNotExist:
        return Response({"detail": "Quiz not found"}, status=status.HTTP_404_NOT_FOUND)

    if not student_has_course_access(request.user, quiz.course):
        return Response({"detail": "You need a package that includes this course."}, status=status.HTTP_403_FORBIDDEN)

    answers = request.data.get("answers")
    if not isinstance(answers, dict):
        return Response({"detail": "answers must be an object mapping question_id -> choice_id"}, status=status.HTTP_400_BAD_REQUEST)

    questions = list(quiz.questions.prefetch_related("choices").all())
    total = len(questions)
    score = 0

    submission = QuizSubmission.objects.create(quiz=quiz, student=request.user, total=total, score=0)

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
    submission.save(update_fields=["score", "total"])

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
def student_quiz_submissions(request):
    student_only(request.user)
    subs = QuizSubmission.objects.select_related("quiz", "quiz__course").filter(student=request.user).order_by("-created_at")
    return Response(QuizSubmissionSerializer(subs, many=True, context={"request": request}).data)


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

# =====================================================
# ADMIN PACKAGE CRUD (NEW)
# =====================================================

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def package_list_create(request):
    if request.method == "GET":
        admin_only(request.user)
        packages = Package.objects.all().order_by("-created_at")
        serializer = PackageSerializer(packages, many=True, context={"request": request})
        return Response(serializer.data)

    admin_only(request.user)
    serializer = PackageCreateSerializer(data=request.data, context={"request": request})
    if serializer.is_valid():
        package = serializer.save()
        return Response(PackageSerializer(package, context={"request": request}).data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
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
        serializer = PackageCreateSerializer(package, data=request.data, partial=True, context={"request": request})
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
