from django.contrib import admin
from .models import User, StudentProfile, TeacherProfile, Course, CourseSection, CourseSubSection

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('email', 'role', 'is_staff', 'date_joined')
    list_filter = ('role', 'is_staff', 'is_active')
    search_fields = ('email', 'username')

@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'user', 'student_class', 'exam_target', 'school')
    search_fields = ('full_name', 'user__email', 'school')

@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'user', 'organization', 'is_verified')
    list_filter = ('is_verified',)
    search_fields = ('full_name', 'user__email', 'organization')

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_by', 'exam_target', 'student_class', 'is_published', 'created_at')
    list_filter = ('is_published', 'exam_target', 'student_class')
    search_fields = ('title', 'description')
    filter_horizontal = ('assigned_teachers',)  # For easy teacher assignment in admin

@admin.register(CourseSection)
class CourseSectionAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'order')
    list_filter = ('course',)
    search_fields = ('title', 'course__title')

@admin.register(CourseSubSection)
class CourseSubSectionAdmin(admin.ModelAdmin):
    list_display = ('title', 'section', 'content_type', 'order')
    list_filter = ('content_type', 'section__course')
    search_fields = ('title', 'section__title')