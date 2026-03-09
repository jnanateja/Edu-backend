from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static

from .media_views import serve_media

urlpatterns = [
    re_path(r'^media/(?P<path>.*)$', serve_media),
    re_path(r'^api/media/(?P<path>.*)$', serve_media),
    path('admin/', admin.site.urls),
    path('api/', include('training_app.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
