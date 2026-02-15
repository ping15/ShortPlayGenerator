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

# 本地生成视频存储目录
GENERATED_VIDEOS_DIR = BASE_DIR / 'generated_videos'

# 启动时是否跳过远程 SSH 初始化（USE_REMOTE_SSH=True 且网络不可达时可设为 true）
SKIP_SSH_INIT_ON_STARTUP = os.environ.get('SKIP_SSH_INIT_ON_STARTUP', 'false').lower() in ('true', '1', 'yes')
