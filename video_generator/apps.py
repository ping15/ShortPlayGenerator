from django.apps import AppConfig


class VideoGeneratorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'video_generator'
    verbose_name = '视频生成'

    def ready(self):
        """项目启动时初始化：连接远程服务器并验证环境"""
        from django.conf import settings
        if getattr(settings, 'SKIP_SSH_INIT_ON_STARTUP', False):
            return
        from .services import video_generator_service
        video_generator_service.initialize()
