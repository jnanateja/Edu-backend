from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings

User = settings.AUTH_USER_MODEL

import uuid
import os

def course_doc_upload_path(instance, filename: str) -> str:
    """Store lecture docs under media/course_docs with a UUID name preserving extension."""
    base, ext = os.path.splitext(filename)
    ext = ext.lower() if ext else ""
    return f"course_docs/{uuid.uuid4().hex}{ext}"


def package_cover_upload_path(instance, filename: str) -> str:
    """Store learning path cover images under media/package_covers with UUID names."""
    base, ext = os.path.splitext(filename)
    ext = ext.lower() if ext else ""
    return f"package_covers/{uuid.uuid4().hex}{ext}"


def quiz_pdf_upload_path(instance, filename: str) -> str:
    """Store quiz PDFs under media/quiz_files with a UUID name preserving extension."""
    base, ext = os.path.splitext(filename)
    ext = ext.lower() if ext else ""
    return f"quiz_files/{uuid.uuid4().hex}{ext}"


# =====================================================
# USER MODEL (AUTH ONLY)
# =====================================================
class User(AbstractUser):
    ROLE_CHOICES = (
        ("student", "Student"),
        ("teacher", "Teacher"),
    )

    email = models.EmailField(unique=True)
    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        blank=True,
        null=True,
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def save(self, *args, **kwargs):
        # Admins are always teachers
        if self.is_staff and not self.role:
            self.role = "teacher"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.email} ({self.role})"


# =====================================================
# STUDENT PROFILE
# =====================================================
class StudentProfile(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="student_profile"
    )

    full_name = models.CharField(max_length=100)
    age = models.PositiveIntegerField()

    student_class = models.CharField(
        max_length=10,
        choices=(("11", "Class 11"), ("12", "Class 12")),
    )

    school = models.CharField(max_length=150)

    exam_target = models.CharField(
        max_length=20,
        choices=(
            ("jee", "JEE"),
            ("neet", "NEET"),
            ("eamcet", "EAMCET"),
        ),
    )

    parent_name = models.CharField(max_length=100, blank=True)
    parent_contact = models.CharField(max_length=15, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Student: {self.full_name}"


# =====================================================
# TEACHER PROFILE
# =====================================================
class TeacherProfile(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="teacher_profile"
    )

    full_name = models.CharField(max_length=100)
    organization = models.CharField(max_length=150)
    qualification = models.CharField(max_length=150)
    experience_years = models.PositiveIntegerField()

    subjects = models.CharField(max_length=200)
    bio = models.TextField(blank=True)

    is_verified = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Teacher: {self.full_name}"


# =====================================================
# COURSE
# =====================================================
class Course(models.Model):
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_courses"
    )

    assigned_teachers = models.ManyToManyField(
        User,
        related_name="assigned_courses",
        blank=True
    )

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    exam_target = models.CharField(
        max_length=20,
        choices=(("jee", "JEE"), ("neet", "NEET"), ("eamcet", "EAMCET")),
    )

    student_class = models.CharField(
        max_length=10,
        choices=(("11", "Class 11"), ("12", "Class 12")),
    )

    # NOTE: In this LMS, a course is considered "published" as soon as it is created/assigned.
    # Package publishing controls storefront visibility.
    is_published = models.BooleanField(default=True)

    # Homepage metadata
    rating = models.FloatField(default=0.0)
    total_enrollments = models.IntegerField(default=0)

    estimated_duration = models.CharField(
        max_length=50,
        blank=True,
        help_text="e.g., '6 months', '12 weeks'"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    def is_teacher_assigned(self, teacher):
        return self.assigned_teachers.filter(id=teacher.id).exists()


# =====================================================
# SECTION
# =====================================================
class CourseSection(models.Model):
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="sections"
    )

    title = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["order"]
        unique_together = ("course", "order")

    def __str__(self):
        return f"{self.course.title} - {self.title}"


# =====================================================
# SUB-SECTION
# =====================================================
class CourseSubSection(models.Model):
    CONTENT_CHOICES = (
        ("video", "Video"),
        ("pdf", "PDF"),
        ("file", "Document"),
    )

    section = models.ForeignKey(
        CourseSection, on_delete=models.CASCADE, related_name="subsections"
    )

    title = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=1)

    content_type = models.CharField(max_length=10, choices=CONTENT_CHOICES)

    video_url = models.URLField(blank=True, null=True)
    pdf_file = models.FileField(upload_to=course_doc_upload_path, blank=True, null=True)

    mux_upload_id = models.CharField(max_length=255, blank=True, null=True)
    mux_asset_id = models.CharField(max_length=255, blank=True, null=True)
    mux_playback_id = models.CharField(max_length=255, blank=True, null=True)
    video_status = models.CharField(max_length=50, blank=True, null=True)
    video_duration = models.FloatField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]
        unique_together = ("section", "order")

    def __str__(self):
        return f"{self.section.title} - {self.title}"


# =====================================================
# PACKAGE (NEW)
# =====================================================
class Package(models.Model):
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_packages"
    )

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    cover_image = models.ImageField(upload_to=package_cover_upload_path, blank=True, null=True)

    # one-time purchase metadata
    is_published = models.BooleanField(default=False)
    featured = models.BooleanField(default=False)

    is_free = models.BooleanField(default=False)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    discounted_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    courses = models.ManyToManyField(Course, related_name="packages", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def get_discount_percentage(self):
        if self.discounted_price and self.price > 0:
            discount = ((self.price - self.discounted_price) / self.price) * 100
            return round(discount, 1)
        return None

    def __str__(self):
        return self.title


# =====================================================
# PACKAGE PURCHASE (NEW) – lifetime access receipt
# =====================================================
class PackagePurchase(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="package_purchases")
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name="purchases")
    status = models.CharField(max_length=20, default="active")  # keep simple for v1
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("student", "package")

    def __str__(self):
        return f"{self.student.email} -> {self.package.title}"


# =====================================================
# QUIZZES
# =====================================================

class Quiz(models.Model):
    QUIZ_TYPE_CHOICES = (
        ("mcq", "MCQ"),
        ("pdf", "PDF Quiz"),
    )

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="quizzes")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_quizzes")

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    quiz_type = models.CharField(max_length=10, choices=QUIZ_TYPE_CHOICES, default="mcq")
    question_pdf = models.FileField(upload_to=quiz_pdf_upload_path, blank=True, null=True)
    answer_key_pdf = models.FileField(upload_to=quiz_pdf_upload_path, blank=True, null=True)

    # Scheduling & rules
    # If due_at is set, students cannot start/submit after this time.
    due_at = models.DateTimeField(null=True, blank=True)

    # If set, the attempt expires after N minutes from start.
    time_limit_minutes = models.PositiveIntegerField(null=True, blank=True)

    # Attempts per student. If 0 => unlimited (kept simple).
    max_attempts = models.PositiveIntegerField(default=1)

    # If False, retakes are disallowed regardless of max_attempts.
    allow_retakes = models.BooleanField(default=True)

    # Quizzes are immediately visible to enrolled students; due/time/attempt rules control access.
    is_published = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.course.title} - {self.title}"


class QuizQuestion(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    prompt = models.TextField()
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["order"]
        unique_together = ("quiz", "order")

    def __str__(self):
        return f"Q{self.order}: {self.prompt[:50]}"


class QuizChoice(models.Model):
    question = models.ForeignKey(QuizQuestion, on_delete=models.CASCADE, related_name="choices")
    text = models.CharField(max_length=400)
    is_correct = models.BooleanField(default=False)

    def __str__(self):
        return f"Choice: {self.text[:40]}"


class QuizSubmission(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="quiz_submissions")

    score = models.IntegerField(default=0)
    total = models.IntegerField(default=0)
    submission_file = models.FileField(upload_to=quiz_pdf_upload_path, blank=True, null=True)
    feedback = models.TextField(blank=True)
    graded_at = models.DateTimeField(null=True, blank=True)
    graded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="graded_quiz_submissions")

    STATUS_CHOICES = (
        ("in_progress", "In Progress"),
        ("submitted", "Submitted"),
        ("expired", "Expired"),
    )

    attempt_number = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="submitted")

    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    time_taken_seconds = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.student.email} - {self.quiz.title} ({self.score}/{self.total})"


class QuizAnswer(models.Model):
    submission = models.ForeignKey(QuizSubmission, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(QuizQuestion, on_delete=models.CASCADE, related_name="answers")
    selected_choice = models.ForeignKey(QuizChoice, on_delete=models.SET_NULL, null=True, blank=True)

    is_correct = models.BooleanField(default=False)

    class Meta:
        unique_together = ("submission", "question")

    def __str__(self):
        return f"Answer {self.question.id} ({'correct' if self.is_correct else 'wrong'})"


# =====================================================
# CLASS SCHEDULES + IN-APP NOTIFICATIONS
# =====================================================


class CourseSchedule(models.Model):
    """Live/virtual class schedules for a specific course."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="schedules")

    # Who created/updated the schedule (teacher/admin)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_schedules")

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    start_at = models.DateTimeField()
    end_at = models.DateTimeField(null=True, blank=True)

    live_link = models.URLField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_at"]

    def __str__(self):
        return f"{self.course.title}: {self.title} ({self.start_at})"


class Notification(models.Model):
    """Simple in-app notifications (no email/push in v1)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)

    # Optional deep-link hints for the frontend
    course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications")
    schedule = models.ForeignKey(CourseSchedule, on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications")
    url = models.CharField(max_length=500, blank=True)

    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Notif({self.user.email}): {self.title}"


# =====================================================
# COURSE ANNOUNCEMENTS (Teacher/Admin -> Students)
# =====================================================


class CourseAnnouncement(models.Model):
    """Course-wide announcements created by teachers/admins.

    Students can view announcements only if they have course access.
    Creating/updating an announcement also creates in-app notifications.
    """

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="announcements")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_announcements")

    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    link = models.URLField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Announcement({self.course.title}): {self.title}"
