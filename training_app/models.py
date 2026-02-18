from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings

User = settings.AUTH_USER_MODEL


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

    is_published = models.BooleanField(default=False)

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
    )

    section = models.ForeignKey(
        CourseSection, on_delete=models.CASCADE, related_name="subsections"
    )

    title = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=1)

    content_type = models.CharField(max_length=10, choices=CONTENT_CHOICES)

    video_url = models.URLField(blank=True, null=True)
    pdf_file = models.FileField(upload_to="course_pdfs/", blank=True, null=True)

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
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="quizzes")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_quizzes")

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    is_published = models.BooleanField(default=False)

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
