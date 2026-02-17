"""
视频 API 路由
"""
from django.urls import path
from .views import CreateVideoView, MergeVideoView

urlpatterns = [
    path('create/', CreateVideoView.as_view(), name='create'),
    path('create', CreateVideoView.as_view(), name='create-no-slash'),
    path('merge/', MergeVideoView.as_view(), name='merge'),
    path('merge', MergeVideoView.as_view(), name='merge-no-slash'),
]
