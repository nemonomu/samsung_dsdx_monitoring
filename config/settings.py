"""
Django settings for monitoring_dsdx project.
5단계 방어 체계를 통한 데이터 품질 확보 모니터링 시스템
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from .config import DB_CONFIG, DB_CONFIG_V2, SERVER_CONFIG

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'your-secret-key-here-change-in-production')

import socket
_hostname = socket.gethostname()
DEBUG = _hostname not in [SERVER_CONFIG['hostname']]  # 운영서버 hostname이면 False, 아니면 True (개발)

ALLOWED_HOSTS = SERVER_CONFIG['allowed_hosts']

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Custom apps - Main
    'apps.main',
    'apps.accounts',
    # DS apps
    'apps.ds.ds_infra',
    'apps.ds.ds_document',
    'apps.ds.ds_layer1',
    'apps.ds.ds_layer2',
    'apps.ds.ds_layer3',
    'apps.ds.ds_layer4',
    # DX apps
    'apps.dx.dx_dashboard',
    'apps.dx.dx_document',
    'apps.dx.dx_data',
    'apps.dx.dx_layer1',
    'apps.dx.dx_layer2',
    'apps.dx.dx_layer3',
    'apps.dx.dx_layer4',
    'apps.dx.dx_layer5',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.accounts.middleware.LoginRequiredMiddleware',  # 로그인 필수
    'apps.common.monitoring_cache.MonitoringCacheInvalidationMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
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

# Database
# Django 기본 DB (세션, 마이그레이션용) - SQLite 사용
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    },
    # DX 데이터 조회용 (PostgreSQL)
    'dx': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'postgres',
        'USER': DB_CONFIG['user'],
        'PASSWORD': DB_CONFIG['password'],
        'HOST': DB_CONFIG['host'],
        'PORT': DB_CONFIG['port'],
    },
    # DS 데이터 조회용 (MySQL)
    'ds': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': DB_CONFIG_V2['database'],
        'USER': DB_CONFIG_V2['user'],
        'PASSWORD': DB_CONFIG_V2['password'],
        'HOST': DB_CONFIG_V2['host'],
        'PORT': DB_CONFIG_V2['port'],
    },
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
]
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Authentication settings
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# Session settings (1시간 타임아웃)
SESSION_COOKIE_AGE = 3600  # 1시간 (초 단위)
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True  # 매 요청마다 세션 갱신 (활동 시 연장)

# Logging 설정 - API 에러 traceback 콘솔 출력
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'apps': {
            'level': 'DEBUG',
            'handlers': ['console'],
            'propagate': False,
        },
    },
}
