import os
from decimal import Decimal
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Variables de entorno
# ---------------------------------------------------------------------------
# Se cargan desde un archivo .env en la raíz del proyecto (ver .env.example).
# Si python-dotenv no está instalado, se usan solo las variables del sistema.
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / '.env')
except ImportError:  # pragma: no cover
    pass


def env(name, default=None):
    value = os.environ.get(name)
    return default if value is None or value == '' else value


def env_bool(name, default=False):
    value = env(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'si', 'sí', 'on')


def env_list(name, default=''):
    return [item.strip() for item in env(name, default).split(',') if item.strip()]


DEBUG = env_bool('DJANGO_DEBUG', True)

# En desarrollo se permite una clave por defecto; en producción es obligatoria.
SECRET_KEY = env('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('Definí DJANGO_SECRET_KEY en el entorno para producción.')
    SECRET_KEY = 'django-insecure-solo-para-desarrollo-local'

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS', '')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'accounts',
    'communities',
    'tickets',
    'donations',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
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
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'config.context_processors.site',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': env('SQLITE_PATH', BASE_DIR / 'db.sqlite3'),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es-ar'
TIME_ZONE = 'America/Argentina/Buenos_Aires'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'accounts.User'

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'communities:list'
LOGOUT_REDIRECT_URL = 'accounts:login'

# Galería de comunidades: máximo de archivos por envío y tamaño por imagen.
DATA_UPLOAD_MAX_NUMBER_FILES = 30
COMMUNITY_IMAGE_MAX_MB = int(env('COMMUNITY_IMAGE_MAX_MB', '8'))

# Cookies seguras cuando el sitio corre con HTTPS (producción).
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_CONTENT_TYPE_NOSNIFF = True

# ---------------------------------------------------------------------------
# Sitio / redes sociales
# ---------------------------------------------------------------------------
SITE_NAME = env('SITE_NAME', 'Semillas del Algarrobo')

# URL pública absoluta del sitio (sin barra final). Se usa para armar las URLs
# de retorno que se envían a Mercado Pago. Ej: https://semillasdelalgarrobo.org
SITE_URL = env('SITE_URL', 'http://127.0.0.1:8000').rstrip('/')

SOCIAL_LINKS = {
    'instagram': env('SOCIAL_INSTAGRAM_URL', 'https://www.instagram.com/semillasdelalgarrobo/'),
    'facebook': env('SOCIAL_FACEBOOK_URL', 'https://www.facebook.com/asistenciasolidariaelalgarrobo/'),
}

# ---------------------------------------------------------------------------
# Mercado Pago
# ---------------------------------------------------------------------------
# NUNCA escribir credenciales reales en este archivo: van en .env.
MERCADOPAGO_ACCESS_TOKEN = env('MERCADOPAGO_ACCESS_TOKEN', '')
MERCADOPAGO_PUBLIC_KEY = env('MERCADOPAGO_PUBLIC_KEY', '')
# "Clave secreta" de Webhooks (Tus integraciones > Webhooks). Se usa para
# validar la firma x-signature de cada notificación.
MERCADOPAGO_WEBHOOK_SECRET = env('MERCADOPAGO_WEBHOOK_SECRET', '')
# Tolerancia (segundos) entre el timestamp firmado y el reloj del servidor.
# 0 = sin control de tiempo (Mercado Pago reintenta notificaciones durante días).
MERCADOPAGO_WEBHOOK_TOLERANCE = int(env('MERCADOPAGO_WEBHOOK_TOLERANCE', '0'))
MERCADOPAGO_CURRENCY = env('MERCADOPAGO_CURRENCY', 'ARS')
# Texto que aparece en el resumen de la tarjeta del donador.
MERCADOPAGO_STATEMENT_DESCRIPTOR = env('MERCADOPAGO_STATEMENT_DESCRIPTOR', 'SEMILLAS ALG')

# Donación única: importes sugeridos y límites (siempre validados en el backend).
DONATION_PRESET_AMOUNTS = [
    Decimal(value) for value in env_list('DONATION_PRESET_AMOUNTS', '5000,10000,20000,50000')
]
DONATION_MIN_AMOUNT = Decimal(env('DONATION_MIN_AMOUNT', '500'))
DONATION_MAX_AMOUNT = Decimal(env('DONATION_MAX_AMOUNT', '5000000'))

# Pesos usados para calcular qué comunidad tiene mayor necesidad.
# Ver communities/priority.py y el README.
NEED_PRIORITY_WEIGHTS = {
    'active_need': 1.0,       # por cada necesidad activa
    'urgent': 3.0,            # extra si está marcada como urgente
    'remaining_ratio': 2.0,   # multiplicado por la fracción que falta cubrir (0 a 1)
    'categories': {           # extra según la categoría
        'Alimentos': 2.0,
        'Agua': 2.0,
        'Salud': 2.0,
        'Educación': 1.0,
        'Vivienda': 1.0,
        'Ropa': 1.0,
        'Otro': 0.0,
    },
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'loggers': {
        'donations': {'handlers': ['console'], 'level': env('DONATIONS_LOG_LEVEL', 'INFO')},
    },
}
