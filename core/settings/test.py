"""Configuração usada apenas pelos testes (pytest).

Banco em memória (SQLite), Celery em modo síncrono e hasher de senha rápido.
"""
from .base import *  # noqa: F401,F403

DEBUG = False

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = False

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

MEDIA_ROOT = BASE_DIR / 'test_media'  # noqa: F405

LOGGING['root']['level'] = 'WARNING'  # noqa: F405