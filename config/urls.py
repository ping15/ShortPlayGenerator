"""
URL configuration for ShortPlayGenerator project.
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('video_generator.urls')),
]
