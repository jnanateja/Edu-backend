from django.db import models
from django.contrib.auth.models import AbstractUser
from django.db import models
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
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

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
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name="courses")

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

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


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
