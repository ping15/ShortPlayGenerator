"""
Django settings for ShortPlayGenerator project.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# 加载 .env（存在则加载，便于服务器部署时用 .env 区分配置）
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-change-me-in-production')

DEBUG = os.environ.get('DEBUG', 'True').lower() == 'true'

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'video_generator.apps.VideoGeneratorConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# DRF
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

# CORS
CORS_ALLOW_ALL_ORIGINS = True

# 执行模式：True=通过SSH连接远程执行，False=本机直接执行（部署到公网服务器时用 False）
# 通过环境变量区分：本地默认 True，服务器设置 USE_REMOTE_SSH=false 即可，无需改代码
USE_REMOTE_SSH = os.environ.get('USE_REMOTE_SSH', 'true').lower() in ('true', '1', 'yes')

# 远程服务器配置（USE_REMOTE_SSH=True 时生效）
REMOTE_SSH_HOST = os.environ.get('REMOTE_SSH_HOST', '')
REMOTE_SSH_PORT = int(os.environ.get('REMOTE_SSH_PORT', '52138'))
REMOTE_SSH_USER = os.environ.get('REMOTE_SSH_USER', 'root')
REMOTE_SSH_PASSWORD = os.environ.get('REMOTE_SSH_PASSWORD', '')

# SkyReels 工作路径（SSH 模式和本机模式共用）
REMOTE_WORK_DIR = os.environ.get('REMOTE_WORK_DIR', '/root/autodl-tmp/SkyReels-V3')
REMOTE_MODEL_ID = os.environ.get('REMOTE_MODEL_ID', '/root/autodl-tmp/SkyReels-V3-R2V-14B')

# 远程生成视频结果目录（按 task_type，校验 taskId.mp4 是否存在）
REMOTE_RESULT_DIR_REFERENCE_TO_VIDEO = os.environ.get(
    'REMOTE_RESULT_DIR_REFERENCE_TO_VIDEO', f'{REMOTE_WORK_DIR}/result/reference_to_video',
)
REMOTE_RESULT_DIR_SINGLE_SHOT_EXTENSION = os.environ.get(
    'REMOTE_RESULT_DIR_SINGLE_SHOT_EXTENSION', f'{REMOTE_WORK_DIR}/result/single_shot_extension',
)

# 本地生成视频存储目录
GENERATED_VIDEOS_DIR = BASE_DIR / 'generated_videos'

# 视频生成/延伸：脚本读取的输入资源路径（远程或本机执行时）
# local: 解析为 file:// 时使用此路径，默认 /home/test_assets
REMOTE_TEST_ASSETS_DIR = os.environ.get('REMOTE_TEST_ASSETS_DIR', '/home/test_assets')

# 视频合成：Django 本机读取的输入资源路径
# local: 解析为 file:// 时使用此路径，默认当前项目 test_assets（跨 Windows/Linux）
MERGE_TEST_ASSETS_DIR = os.environ.get('MERGE_TEST_ASSETS_DIR') or (BASE_DIR / 'test_assets')

# 启动时是否跳过远程 SSH 初始化（USE_REMOTE_SSH=True 且网络不可达时可设为 true）
SKIP_SSH_INIT_ON_STARTUP = os.environ.get('SKIP_SSH_INIT_ON_STARTUP', 'false').lower() in ('true', '1', 'yes')

# 通知日志路径（merge/create 完成时追加），默认 test_assets/logs/（跨 Windows/Linux）
NOTIFY_LOG_PATH = os.environ.get('NOTIFY_LOG_PATH') or str(BASE_DIR / 'test_assets' / 'logs' / 'shortplay_notify.log')

# 对象存储配置（腾讯云 COS，merge 完成后上传并记录 URL）
# 使用 cos-python-sdk-v5，需配置 SecretId/SecretKey/Bucket/Region
OSS_ACCESS_KEY_ID = os.environ.get('OSS_ACCESS_KEY_ID', '')      # 即 COS SecretId
OSS_ACCESS_KEY_SECRET = os.environ.get('OSS_ACCESS_KEY_SECRET', '')  # 即 COS SecretKey
OSS_BUCKET_NAME = os.environ.get('OSS_BUCKET_NAME', '')        # 如 aivideo-1382153705
OSS_REGION = os.environ.get('OSS_REGION', 'ap-beijing')        # 如 ap-beijing
# 合并视频 OSS 对象前缀，如 merged/
OSS_MERGED_PREFIX = os.environ.get('OSS_MERGED_PREFIX', 'merged/')
# 生成/延伸视频 OSS 对象前缀，如 generated/
OSS_CREATE_PREFIX = os.environ.get('OSS_CREATE_PREFIX', 'generated/')
# OSS 上传后 URL 记录日志（merge 与 create 各一份）
OSS_URL_LOG_PATH = os.environ.get('OSS_URL_LOG_PATH') or str(BASE_DIR / 'test_assets' / 'logs' / 'merged_oss_urls.log')
OSS_CREATE_URL_LOG_PATH = os.environ.get('OSS_CREATE_URL_LOG_PATH') or str(BASE_DIR / 'test_assets' / 'logs' / 'video_create_oss_urls.log')

# 任务完成后的 HTTP 通知地址（POST JSON，有值则调用）
MERGE_NOTIFY_URL = os.environ.get('MERGE_NOTIFY_URL', '')
VIDEO_CREATE_NOTIFY_URL = os.environ.get('VIDEO_CREATE_NOTIFY_URL', '')
