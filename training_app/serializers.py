from django.utils import timezone
from urllib.parse import urljoin
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.conf import settings
from .models import (
    User, StudentProfile, TeacherProfile,
    Course, CourseSection, CourseSubSection,
    Package, PackagePurchase,
    Quiz, QuizQuestion, QuizChoice, QuizSubmission, QuizAnswer,
    CourseSchedule, Notification, CourseAnnouncement,
)
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


def absolute_media_url(request, url: str | None):
    if not url:
        return None

    public_base = getattr(settings, "PUBLIC_BASE_URL", "").strip()

    if request:
        built = request.build_absolute_uri(url)
        if public_base:
            try:
                host = request.get_host().split(":")[0]
            except Exception:
                host = ""
            if host in {"127.0.0.1", "localhost", "10.0.2.2"}:
                return urljoin(f"{public_base.rstrip('/')}/", url.lstrip("/"))
        return built

    if public_base:
        return urljoin(f"{public_base.rstrip('/')}/", url.lstrip("/"))

    return url


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)

        data["user"] = {
            "id": self.user.id,
            "email": self.user.email,
            "role": self.user.role,
            "is_admin": self.user.is_staff,
        }

        return data


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    # student fields
    full_name = serializers.CharField(required=False)
    age = serializers.IntegerField(required=False)
    student_class = serializers.CharField(required=False)
    school = serializers.CharField(required=False)
    exam_target = serializers.CharField(required=False)

    # teacher fields
    organization = serializers.CharField(required=False)
    qualification = serializers.CharField(required=False)
    experience_years = serializers.IntegerField(required=False)
    subjects = serializers.CharField(required=False)

    class Meta:
        model = User
        fields = (
            "email",
            "password",
            "role",
            "full_name",
            "age",
            "student_class",
            "school",
            "exam_target",
            "organization",
            "qualification",
            "experience_years",
            "subjects",
        )

    def create(self, validated_data):
        role = validated_data.pop("role")

        user = User.objects.create_user(
            username=validated_data["email"],
            email=validated_data["email"],
            password=validated_data["password"],
            role=role,
        )

        if role == "student":
            StudentProfile.objects.create(
                user=user,
                full_name=validated_data.get("full_name", ""),
                age=validated_data.get("age", 0),
                student_class=validated_data.get("student_class", "11"),
                school=validated_data.get("school", ""),
                exam_target=validated_data.get("exam_target", "jee"),
            )

        elif role == "teacher":
            TeacherProfile.objects.create(
                user=user,
                full_name=validated_data.get("full_name", ""),
                organization=validated_data.get("organization", ""),
                qualification=validated_data.get("qualification", ""),
                experience_years=validated_data.get("experience_years", 0),
                subjects=validated_data.get("subjects", ""),
            )

        return user


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "full_name", "role", "is_staff")

    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        if obj.role == "teacher" and hasattr(obj, "teacher_profile"):
            return obj.teacher_profile.full_name
        elif obj.role == "student" and hasattr(obj, "student_profile"):
            return obj.student_profile.full_name
        return obj.get_full_name() or obj.email


class CourseSubSectionSerializer(serializers.ModelSerializer):
    mux_playback_token = serializers.SerializerMethodField()
    pdf_file = serializers.SerializerMethodField()

    class Meta:
        model = CourseSubSection
        fields = (
            "id",
            "section",
            "title",
            "order",
            "content_type",
            "video_url",
            "pdf_file",
            "mux_upload_id",
            "mux_asset_id",
            "mux_playback_id",
            "mux_playback_token",
            "video_status",
            "video_duration",
            "created_at",
        )
        read_only_fields = (
            "mux_upload_id",
            "mux_asset_id",
            "mux_playback_id",
            "mux_playback_token",
            "video_status",
            "video_duration",
            "created_at",
        )

    def get_mux_playback_token(self, obj):
        if not obj.mux_playback_id:
            return None

        request = self.context.get("request")
        if not request or not getattr(request, "user", None) or not request.user.is_authenticated:
            return None

        try:
            from .views import _generate_mux_playback_token
            return _generate_mux_playback_token(obj.mux_playback_id)
        except Exception:
            return None

    def get_pdf_file(self, obj):
        return absolute_media_url(self.context.get("request"), obj.pdf_file.url if obj.pdf_file else None)


class CourseSectionSerializer(serializers.ModelSerializer):
    subsections = CourseSubSectionSerializer(many=True, read_only=True)

    class Meta:
        model = CourseSection
        fields = ("id", "course", "title", "order", "subsections")


class CourseCreateSerializer(serializers.ModelSerializer):
    assigned_teacher_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        allow_empty=True,
        default=[],
    )

    class Meta:
        model = Course
        fields = (
            "title",
            "description",
            "exam_target",
            "student_class",
            "is_published",
            "estimated_duration",
            "assigned_teacher_ids",
        )

    def validate_assigned_teacher_ids(self, value):
        if value:
            teacher_users = User.objects.filter(id__in=value, role="teacher")
            found_ids = set(teacher_users.values_list("id", flat=True))
            invalid_ids = set(value) - found_ids
            if invalid_ids:
                raise serializers.ValidationError(
                    f"Invalid teacher IDs: {', '.join(map(str, invalid_ids))}"
                )
        return value

    def create(self, validated_data):
        teacher_ids = validated_data.pop("assigned_teacher_ids", [])
        user = self.context["request"].user

        course = Course.objects.create(
            created_by=user,
            title=validated_data["title"],
            description=validated_data.get("description", ""),
            exam_target=validated_data["exam_target"],
            student_class=validated_data["student_class"],
            # Courses are treated as published once created/assigned. Packages control storefront visibility.
            is_published=True,
            estimated_duration=validated_data.get("estimated_duration", ""),
        )

        if teacher_ids:
            teachers = User.objects.filter(id__in=teacher_ids, role="teacher")
            course.assigned_teachers.add(*teachers)

        return course


class CourseSerializer(serializers.ModelSerializer):
    sections = CourseSectionSerializer(many=True, read_only=True)
    created_by = UserSerializer(read_only=True)
    assigned_teachers = UserSerializer(many=True, read_only=True)

    is_assigned = serializers.SerializerMethodField()
    sections_count = serializers.SerializerMethodField()
    subsections_count = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = (
            "id",
            "title",
            "description",
            "exam_target",
            "student_class",
            "is_published",
                        "rating",
            "total_enrollments",
            "estimated_duration",
            "created_at",
            "updated_at",
            "sections",
            "created_by",
            "assigned_teachers",
            "is_assigned",
            "sections_count",
            "subsections_count",
        )
        read_only_fields = (
            "created_by",
            "assigned_teachers",
            "created_at",
            "updated_at",
            "rating",
            "total_enrollments",
        )

    def get_is_assigned(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.is_teacher_assigned(request.user)
        return False

    def get_sections_count(self, obj):
        return obj.sections.count()

    def get_subsections_count(self, obj):
        return CourseSubSection.objects.filter(section__course=obj).count()


# =====================================================
# PACKAGE SERIALIZERS (NEW)
# =====================================================

class PackageSerializer(serializers.ModelSerializer):
    courses = CourseSerializer(many=True, read_only=True)
    discount_percentage = serializers.SerializerMethodField()
    cover_image = serializers.SerializerMethodField()

    class Meta:
        model = Package
        fields = (
            "id",
            "title",
            "description",
            "cover_image",
            "is_published",
            "featured",
            "is_free",
            "price",
            "discounted_price",
            "discount_percentage",
            "courses",
            "created_at",
            "updated_at",
        )

    def get_discount_percentage(self, obj):
        if obj.discounted_price and obj.price and obj.price > 0:
            discount = ((obj.price - obj.discounted_price) / obj.price) * 100
            return round(discount, 1)
        return None

    def get_cover_image(self, obj):
        if not obj.cover_image:
            return None
        request = self.context.get("request")
        url = obj.cover_image.url
        return absolute_media_url(request, url)


class PackageCourseSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ("id", "title", "exam_target", "student_class", "is_published")


class PackageListSerializer(serializers.ModelSerializer):
    courses = PackageCourseSummarySerializer(many=True, read_only=True)
    discount_percentage = serializers.SerializerMethodField()
    cover_image = serializers.SerializerMethodField()

    class Meta:
        model = Package
        fields = (
            "id",
            "title",
            "description",
            "cover_image",
            "is_published",
            "featured",
            "is_free",
            "price",
            "discounted_price",
            "discount_percentage",
            "courses",
            "created_at",
            "updated_at",
        )

    def get_discount_percentage(self, obj):
        if obj.discounted_price and obj.price and obj.price > 0:
            discount = ((obj.price - obj.discounted_price) / obj.price) * 100
            return round(discount, 1)
        return None

    def get_cover_image(self, obj):
        if not obj.cover_image:
            return None
        request = self.context.get("request")
        url = obj.cover_image.url
        return absolute_media_url(request, url)

class PackageCreateSerializer(serializers.ModelSerializer):
    course_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        allow_empty=True,
        default=[],
        help_text="List of course IDs to include in this package"
    )

    class Meta:
        model = Package
        fields = (
            "title",
            "description",
            "cover_image",
            "is_published",
            "featured",
            "is_free",
            "price",
            "discounted_price",
            "course_ids",
        )

    def validate(self, data):
        is_free = data.get("is_free", False)
        price = data.get("price", 0)
        discounted_price = data.get("discounted_price")

        if is_free:
            if price and price > 0:
                raise serializers.ValidationError({"price": "Price must be 0 for free packages"})
            if discounted_price and discounted_price > 0:
                raise serializers.ValidationError({"discounted_price": "Discounted price must be 0 for free packages"})
        else:
            if not price or price <= 0:
                raise serializers.ValidationError({"price": "Price is required and must be greater than 0 for paid packages"})
            if discounted_price:
                if discounted_price <= 0:
                    raise serializers.ValidationError({"discounted_price": "Discounted price must be greater than 0"})
                if discounted_price >= price:
                    raise serializers.ValidationError({"discounted_price": "Discounted price must be less than original price"})

        return data

    def create(self, validated_data):
        course_ids = validated_data.pop("course_ids", [])
        user = self.context["request"].user

        package = Package.objects.create(
            created_by=user,
            title=validated_data["title"],
            description=validated_data.get("description", ""),
            cover_image=validated_data.get("cover_image"),
            is_published=validated_data.get("is_published", False),
            featured=validated_data.get("featured", False),
            is_free=validated_data.get("is_free", False),
            price=validated_data.get("price", 0.00),
            discounted_price=validated_data.get("discounted_price"),
        )

        if course_ids:
            # Only allow published courses to be bundled into a published package.
            # (Admin can still draft a package with unpublished courses by keeping
            # the package itself unpublished.)
            courses_qs = Course.objects.filter(id__in=course_ids)

            if validated_data.get("is_published", False):
                courses_qs = courses_qs.filter(is_published=True)

            package.courses.add(*courses_qs)

        return package

    def update(self, instance, validated_data):
        course_ids = validated_data.pop("course_ids", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # If course_ids provided, replace the package's course set
        if course_ids is not None:
            courses_qs = Course.objects.filter(id__in=course_ids)
            if instance.is_published:
                courses_qs = courses_qs.filter(is_published=True)
            instance.courses.set(courses_qs)

        return instance


class PackagePurchaseSerializer(serializers.ModelSerializer):
    package = PackageSerializer(read_only=True)

    class Meta:
        model = PackagePurchase
        fields = ("id", "package", "status", "created_at")


# =====================================================
# QUIZ SERIALIZERS
# =====================================================

class QuizFileUrlMixin:
    def _file_url(self, f):
        if not f:
            return None
        request = self.context.get("request")
        url = f.url
        return absolute_media_url(request, url)

    def _student_can_view_answer_key(self, quiz, submission=None):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False

        role = getattr(user, "role", None)
        if user.is_staff or role == "teacher":
            return True
        if role != "student":
            return False

        now = timezone.now()
        if quiz.due_at and now <= quiz.due_at:
            return False

        if submission is None:
            submission = (
                quiz.submissions.filter(student=user, graded_at__isnull=False)
                .order_by("-graded_at", "-created_at")
                .first()
            )

        return bool(submission and submission.graded_at)


class QuizChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuizChoice
        fields = ("id", "text")


class QuizChoiceAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuizChoice
        fields = ("id", "text", "is_correct")


class QuizQuestionSerializer(serializers.ModelSerializer):
    choices = QuizChoiceSerializer(many=True, read_only=True)

    class Meta:
        model = QuizQuestion
        fields = ("id", "prompt", "order", "choices")


class QuizQuestionAdminSerializer(serializers.ModelSerializer):
    choices = QuizChoiceAdminSerializer(many=True, read_only=True)

    class Meta:
        model = QuizQuestion
        fields = ("id", "prompt", "order", "choices")


class QuizSerializer(QuizFileUrlMixin, serializers.ModelSerializer):
    questions = QuizQuestionSerializer(many=True, read_only=True)
    question_pdf = serializers.SerializerMethodField()
    answer_key_pdf = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = (
            "id",
            "course",
            "title",
            "description",
            "quiz_type",
            "question_pdf",
            "answer_key_pdf",
            "is_published",
            "due_at",
            "time_limit_minutes",
            "max_attempts",
            "allow_retakes",
            "created_at",
            "updated_at",
            "questions",
        )
        read_only_fields = ("created_at", "updated_at")

    def get_question_pdf(self, obj):
        return self._file_url(obj.question_pdf)

    def get_answer_key_pdf(self, obj):
        return self._file_url(obj.answer_key_pdf) if self._student_can_view_answer_key(obj) else None


# -----------------------------
# Student-facing "mini" serializers for Grades / Review
# -----------------------------


class CourseMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ("id", "title")


class QuizMiniSerializer(QuizFileUrlMixin, serializers.ModelSerializer):
    course = CourseMiniSerializer(read_only=True)
    question_pdf = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = (
            "id",
            "title",
            "description",
            "course",
            "quiz_type",
            "question_pdf",
            "due_at",
            "time_limit_minutes",
            "max_attempts",
            "allow_retakes",
        )

    def get_question_pdf(self, obj):
        return self._file_url(obj.question_pdf)


class QuizAdminSerializer(QuizFileUrlMixin, serializers.ModelSerializer):
    questions = QuizQuestionAdminSerializer(many=True, read_only=True)
    question_pdf = serializers.SerializerMethodField()
    answer_key_pdf = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = (
            "id",
            "course",
            "title",
            "description",
            "quiz_type",
            "question_pdf",
            "answer_key_pdf",
            "is_published",
            "due_at",
            "time_limit_minutes",
            "max_attempts",
            "allow_retakes",
            "created_at",
            "updated_at",
            "questions",
        )
        read_only_fields = ("created_at", "updated_at")

    def get_question_pdf(self, obj):
        return self._file_url(obj.question_pdf)

    def get_answer_key_pdf(self, obj):
        return self._file_url(obj.answer_key_pdf)


class QuizCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Quiz
        fields = ("title", "description", "quiz_type", "question_pdf", "answer_key_pdf", "is_published", "due_at", "time_limit_minutes", "max_attempts", "allow_retakes")

    def validate(self, attrs):
        quiz_type = attrs.get("quiz_type") or getattr(self.instance, "quiz_type", "mcq")
        question_pdf = attrs.get("question_pdf") or getattr(self.instance, "question_pdf", None)
        if quiz_type == "pdf" and not question_pdf:
            raise serializers.ValidationError({"question_pdf": "Question PDF is required for PDF quizzes."})
        if quiz_type == "pdf":
            attrs["time_limit_minutes"] = None
            attrs["max_attempts"] = 1
            attrs["allow_retakes"] = False
        else:
            allow_retakes = attrs.get("allow_retakes")
            if allow_retakes is False:
                attrs["max_attempts"] = 1
        # Quizzes are always published when created — multipart FormData sends missing
        # booleans as False in DRF, so we force is_published=True for new quizzes.
        if not self.instance:
            attrs["is_published"] = True
        return attrs


class QuizQuestionCreateSerializer(serializers.ModelSerializer):
    choices = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=True,
        help_text="List of choices: [{'text': 'A', 'is_correct': true}, ...]"
    )

    class Meta:
        model = QuizQuestion
        fields = ("prompt", "order", "choices")

    def validate_choices(self, value):
        if not value or len(value) < 2:
            raise serializers.ValidationError("At least 2 choices are required.")
        correct = [c for c in value if c.get("is_correct")]
        if len(correct) != 1:
            raise serializers.ValidationError("Exactly 1 correct choice is required.")
        for c in value:
            if not c.get("text"):
                raise serializers.ValidationError("Each choice must have text.")
        return value


class QuizSubmissionSerializer(QuizFileUrlMixin, serializers.ModelSerializer):
    quiz = QuizMiniSerializer(read_only=True)
    submission_file = serializers.SerializerMethodField()
    graded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = QuizSubmission
        fields = (
            "id",
            "quiz",
            "score",
            "total",
            "attempt_number",
            "status",
            "submission_file",
            "feedback",
            "graded_at",
            "graded_by_name",
            "started_at",
            "submitted_at",
            "time_taken_seconds",
            "created_at",
        )

    def get_submission_file(self, obj):
        return self._file_url(obj.submission_file)

    def get_graded_by_name(self, obj):
        if obj.graded_by_id and hasattr(obj.graded_by, "teacher_profile"):
            return obj.graded_by.teacher_profile.full_name
        return obj.graded_by.email if obj.graded_by_id else None


class QuizChoiceReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuizChoice
        fields = ("id", "text", "is_correct")


class QuizQuestionReviewSerializer(serializers.ModelSerializer):
    choices = QuizChoiceReviewSerializer(many=True, read_only=True)
    selected_choice_id = serializers.SerializerMethodField()

    class Meta:
        model = QuizQuestion
        fields = ("id", "prompt", "order", "choices", "selected_choice_id")

    def get_selected_choice_id(self, obj):
        # We inject answers_by_question into context to avoid N+1.
        answers_by_q = self.context.get("answers_by_question", {})
        ans = answers_by_q.get(obj.id)
        return getattr(ans, "selected_choice_id", None)


class QuizReviewSerializer(QuizFileUrlMixin, serializers.ModelSerializer):
    course = CourseMiniSerializer(read_only=True)
    questions = QuizQuestionReviewSerializer(many=True, read_only=True)
    question_pdf = serializers.SerializerMethodField()
    answer_key_pdf = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = (
            "id",
            "title",
            "description",
            "quiz_type",
            "course",
            "question_pdf",
            "answer_key_pdf",
            "due_at",
            "time_limit_minutes",
            "max_attempts",
            "allow_retakes",
            "questions",
        )

    def get_question_pdf(self, obj):
        return self._file_url(obj.question_pdf)

    def get_answer_key_pdf(self, obj):
        submission = self.context.get("submission")
        return self._file_url(obj.answer_key_pdf) if self._student_can_view_answer_key(obj, submission=submission) else None


class QuizSubmissionReviewSerializer(QuizFileUrlMixin, serializers.ModelSerializer):
    quiz = QuizReviewSerializer(read_only=True)
    submission_file = serializers.SerializerMethodField()

    class Meta:
        model = QuizSubmission
        fields = (
            "id",
            "quiz",
            "score",
            "total",
            "attempt_number",
            "status",
            "submission_file",
            "feedback",
            "graded_at",
            "started_at",
            "submitted_at",
            "time_taken_seconds",
            "created_at",
        )

    def get_submission_file(self, obj):
        return self._file_url(obj.submission_file)


class TeacherQuizSubmissionRowSerializer(QuizFileUrlMixin, serializers.ModelSerializer):
    student = UserSerializer(read_only=True)
    submission_file = serializers.SerializerMethodField()

    class Meta:
        model = QuizSubmission
        fields = (
            "id",
            "student",
            "score",
            "total",
            "attempt_number",
            "status",
            "submission_file",
            "feedback",
            "graded_at",
            "started_at",
            "submitted_at",
            "time_taken_seconds",
            "created_at",
        )

    def get_submission_file(self, obj):
        return self._file_url(obj.submission_file)


# =====================================================
# SCHEDULES + NOTIFICATIONS
# =====================================================


class CourseScheduleSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source="course.title", read_only=True)

    class Meta:
        model = CourseSchedule
        fields = [
            "id",
            "course",
            "course_title",
            "title",
            "description",
            "start_at",
            "end_at",
            "live_link",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["course", "created_by", "created_at", "updated_at"]


class NotificationSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source="course.title", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "title",
            "message",
            "url",
            "is_read",
            "created_at",
            "course",
            "course_title",
            "schedule",
        ]


class CourseAnnouncementSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source="course.title", read_only=True)

    class Meta:
        model = CourseAnnouncement
        fields = [
            "id",
            "course",
            "course_title",
            "title",
            "message",
            "link",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["course", "created_by", "created_at", "updated_at"]
