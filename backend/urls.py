from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView

from .media_views import serve_media

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("training_app.urls")),

    re_path(r"^media/(?P<path>.*)$", serve_media),
    re_path(r"^api/media/(?P<path>.*)$", serve_media),

    re_path(
        r"^(?!api/|admin/|media/|static/|assets/).*$",
        TemplateView.as_view(template_name="index.html"),
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)