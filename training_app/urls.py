from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    register_view,
    login_view,

    # courses
    course_list_create,
    course_detail,
    featured_courses,
    public_courses,

    # teacher assignment
    teacher_course_list,
    teacher_course_detail,
    teacher_list,
    course_teachers,
    assign_teacher,
    remove_teacher,

    # sections
    section_list_create,
    section_detail,
    subsection_list_create,
    subsection_detail,

    # student
    student_course_list,
    student_course_detail,
    student_subsection_detail,

    # packages
    public_packages,
    featured_packages,
    package_public_detail,
    package_list_create,
    package_detail,
    purchase_package,
    student_purchases,

    # quizzes
    course_quiz_list_create,
    quiz_detail,
    quiz_add_question,
    quiz_submit,
    student_quiz_submissions,
    teacher_quiz_submissions,
)

urlpatterns = [
    # AUTH
    path("register/", register_view),
    path("login/", login_view),
    path("token/refresh/", TokenRefreshView.as_view()),

    # COURSES
    path("courses/", course_list_create),
    path("courses/<int:pk>/", course_detail),

    # PUBLIC COURSES
    path("courses/featured/", featured_courses),
    path("courses/public/", public_courses),

    # TEACHERS
    path("teacher/courses/", teacher_course_list),
    path("teacher/courses/<int:pk>/", teacher_course_detail),
    path("teachers/", teacher_list),
    path("courses/<int:pk>/teachers/", course_teachers),
    path("courses/<int:pk>/assign-teacher/", assign_teacher),
    path("courses/<int:pk>/remove-teacher/", remove_teacher),

    # SECTIONS
    path("sections/", section_list_create),
    path("sections/<int:pk>/", section_detail),

    # SUBSECTIONS
    path("subsections/", subsection_list_create),
    path("subsections/<int:pk>/", subsection_detail),

    # STUDENT COURSES
    path("student/courses/", student_course_list),
    path("student/courses/<int:pk>/", student_course_detail),
    path("student/subsections/<int:pk>/", student_subsection_detail),

    # QUIZZES
    path("courses/<int:course_id>/quizzes/", course_quiz_list_create),
    path("quizzes/<int:quiz_id>/", quiz_detail),
    path("quizzes/<int:quiz_id>/questions/", quiz_add_question),
    path("student/quizzes/<int:quiz_id>/submit/", quiz_submit),

    # PUBLIC PACKAGES
    path("packages/public/", public_packages),
    path("packages/featured/", featured_packages),
    path("packages/public/<int:pk>/", package_public_detail),

    # ADMIN PACKAGES
    path("packages/", package_list_create),
    path("packages/<int:pk>/", package_detail),

    # STUDENT QUIZ SUBMISSIONS
    path("student/quiz-submissions/", student_quiz_submissions),

    # TEACHER QUIZ SUBMISSIONS
    path("teacher/quizzes/<int:quiz_id>/submissions/", teacher_quiz_submissions),

    # STUDENT PURCHASE
    path("packages/<int:pk>/purchase/", purchase_package),
    path("student/purchases/", student_purchases),
]
