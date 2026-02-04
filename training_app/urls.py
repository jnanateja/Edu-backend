from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from .views import (
    register_view,
    course_list_create,
    course_detail,
    section_list_create,
    section_detail,
    subsection_list_create,
    subsection_detail,
    login_view,
    student_course_list,
    student_course_detail,
    student_subsection_detail,
)

urlpatterns = [
    # AUTH
    path("register/", register_view),
    path("login/", login_view), 
    path("token/refresh/", TokenRefreshView.as_view()),

    # COURSES
    path("courses/", course_list_create),
    path("courses/<int:pk>/", course_detail),

    # SECTIONS
    path("sections/", section_list_create),
    path("sections/<int:pk>/", section_detail),

    # SUB-SECTIONS
    path("subsections/", subsection_list_create),
    path("subsections/<int:pk>/", subsection_detail),

    # Students
    path("student/courses/", student_course_list),
    path("student/courses/<int:pk>/", student_course_detail),
    path("student/subsections/<int:pk>/", student_subsection_detail),
]

