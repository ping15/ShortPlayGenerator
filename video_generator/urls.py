"""
视频生成 API 路由
"""
from django.urls import path
from .views import GenerateVideoView

urlpatterns = [
    path('generate-video/', GenerateVideoView.as_view(), name='generate-video'),
]
