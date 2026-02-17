"""
URL configuration for ShortPlayGenerator project.
"""
from django.contrib import admin
from django.urls import path, include

from video_generator.views_media import serve_test_asset

urlpatterns = [
    path('admin/', admin.site.urls),
    path('ai/video/', include('video_generator.urls')),
    path('media/test/<path:subpath>', serve_test_asset),
]
