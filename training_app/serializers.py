from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import User, StudentProfile, TeacherProfile, Course, CourseSection, CourseSubSection

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)

        # Add user info
        data["user"] = {
            "id": self.user.id,
            "email": self.user.email,
            "role": self.user.role,
        }

        return data


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, validators=[validate_password]
    )

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

        # Create user
        user = User.objects.create_user(
            username=validated_data["email"],  # internal username
            email=validated_data["email"],
            password=validated_data["password"],
            role=role,
        )

        # Create student profile
        if role == "student":
            StudentProfile.objects.create(
                user=user,
                full_name=validated_data.get("full_name", ""),
                age=validated_data.get("age", 0),
                student_class=validated_data.get("student_class", "11"),
                school=validated_data.get("school", ""),
                exam_target=validated_data.get("exam_target", "jee"),
            )

        # Create teacher profile
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


class CourseSubSectionSerializer(serializers.ModelSerializer):
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
            "created_at",
        )

    def validate(self, data):
        ctype = data.get("content_type")

        video = data.get("video_url")
        pdf = data.get("pdf_file")

        if ctype == "video":
            if not video:
                raise serializers.ValidationError(
                    {"video_url": "Video URL required for video type."}
                )
            if pdf:
                raise serializers.ValidationError(
                    {"pdf_file": "PDF not allowed for video type."}
                )

        if ctype == "pdf":
            if not pdf:
                raise serializers.ValidationError(
                    {"pdf_file": "PDF file required for pdf type."}
                )
            if video:
                raise serializers.ValidationError(
                    {"video_url": "Video URL not allowed for pdf type."}
                )

        return data



class CourseSectionSerializer(serializers.ModelSerializer):
    subsections = CourseSubSectionSerializer(many=True, read_only=True)

    class Meta:
        model = CourseSection
        fields = ("id", "course", "title", "order", "subsections")


class CourseSerializer(serializers.ModelSerializer):
    sections = CourseSectionSerializer(many=True, read_only=True)

    class Meta:
        model = Course
        fields = (
            "id",
            "title",
            "description",
            "exam_target",
            "student_class",
            "is_published",
            "created_at",
            "sections",
        )
