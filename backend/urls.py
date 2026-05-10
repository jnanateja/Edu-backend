from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse

from .media_views import serve_media


def home(request):
    return JsonResponse({
        "message": "Backend is running",
        "status": "ok"
    })


urlpatterns = [
    path("", home),
    path("admin/", admin.site.urls),
    path("api/", include("training_app.urls")),

    re_path(r"^media/(?P<path>.*)$", serve_media),
    re_path(r"^api/media/(?P<path>.*)$", serve_media),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)