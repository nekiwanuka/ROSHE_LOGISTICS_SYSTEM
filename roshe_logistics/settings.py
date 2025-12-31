"""
Django settings for roshe_logistics project.
Roshe Logistics Management System (Web)
"""
import sys
from pathlib import Path
from decouple import Csv, config

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config("SECRET_KEY", default="").strip()
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is not set. Create a .env file (see .env.example) or set the SECRET_KEY environment variable."
    )

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config("DEBUG", default=False, cast=bool)

# Developer convenience: allow `manage.py runserver` to behave like a typical
# development setup (serving static files, detailed errors), even if a
# production-like .env has DEBUG=False.
if "runserver" in sys.argv and not DEBUG:
    DEBUG = True

# NOTE:
# In production you must set a strict ALLOWED_HOSTS list.
# During local development it's common to run `manage.py runserver` while still
# using a production-like .env; in that case, ensure localhost works.
ALLOWED_HOSTS = [
    host.strip()
    for host in config(
        "ALLOWED_HOSTS",
        default="localhost,127.0.0.1",
        cast=Csv(),
    )
    if host and host.strip()
]

_local_dev_hosts = ["localhost", "127.0.0.1", "[::1]"]

# If env parsing resulted in an empty list, fall back to safe local defaults.
if not ALLOWED_HOSTS:
    ALLOWED_HOSTS = list(_local_dev_hosts)

# When using Django's dev server, allow local hosts even if a production domain
# is configured in ALLOWED_HOSTS.
if "runserver" in sys.argv:
    for _h in _local_dev_hosts:
        if _h not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(_h)

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'logistics',  # Our main app
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

ROOT_URLCONF = 'roshe_logistics.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'logistics' / 'templates'],
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

WSGI_APPLICATION = 'roshe_logistics.wsgi.application'

# Database
# Prefer Postgres when configured, but fall back to SQLite at startup if Postgres
# is unreachable/misconfigured (so the app can still boot).
DB_ENGINE = config("DB_ENGINE", default="sqlite").strip().lower()


def _sqlite_databases():
    return {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': config("SQLITE_PATH", default=str(BASE_DIR / 'db.sqlite3')),
        }
    }


def _postgres_databases():
    return {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config("DB_NAME", default="").strip(),
            'USER': config("DB_USER", default="").strip(),
            'PASSWORD': config("DB_PASSWORD", default=""),
            'HOST': config("DB_HOST", default="localhost").strip(),
            'PORT': config("DB_PORT", default="5432").strip(),
        }
    }


def _postgres_is_reachable(postgres_settings: dict) -> bool:
    name = postgres_settings.get('NAME')
    user = postgres_settings.get('USER')
    password = postgres_settings.get('PASSWORD')
    host = postgres_settings.get('HOST')
    port = postgres_settings.get('PORT')

    if not (name and user and password and host and port):
        return False

    try:
        import psycopg2  # provided by psycopg2-binary
    except Exception:
        return False

    try:
        connect_timeout = int(config("DB_CONNECT_TIMEOUT", default="3"))
    except Exception:
        connect_timeout = 3

    try:
        conn = psycopg2.connect(
            dbname=name,
            user=user,
            password=password,
            host=host,
            port=port,
            connect_timeout=connect_timeout,
        )
        conn.close()
        return True
    except Exception as exc:
        return False


def _should_fallback_to_sqlite() -> bool:
    # In local development, prefer booting even if Postgres isn't available.
    if "runserver" in sys.argv:
        return True

    # In production, do NOT silently fall back unless explicitly allowed.
    return config("POSTGRES_FALLBACK_TO_SQLITE", default=False, cast=bool)


if DB_ENGINE in {"postgres", "postgresql", "psql"}:
    _pg = _postgres_databases()['default']
    if _postgres_is_reachable(_pg):
        DATABASES = {'default': _pg}
    else:
        if _should_fallback_to_sqlite():
            print(
                "Postgres is configured but unreachable at startup; falling back to SQLite.",
                file=sys.stderr,
            )
            DATABASES = _sqlite_databases()
        else:
            raise RuntimeError(
                "Postgres is configured but unreachable. Fix DB_* settings, install psycopg2-binary, "
                "or set POSTGRES_FALLBACK_TO_SQLITE=True to allow SQLite fallback."
            )
else:
    DATABASES = _sqlite_databases()

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in config(
        "CSRF_TRUSTED_ORIGINS",
        default="",
        cast=Csv(),
    )
    if origin and origin.strip()
]

# If you run behind a reverse proxy (nginx) terminating TLS, set this in .env:
# SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https
SECURE_PROXY_SSL_HEADER = None
_proxy_header = config("SECURE_PROXY_SSL_HEADER", default="").strip()
if _proxy_header:
    parts = [p.strip() for p in _proxy_header.split(",", 1)]
    if len(parts) == 2:
        SECURE_PROXY_SSL_HEADER = (parts[0], parts[1])

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Kampala'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'logistics' / 'static',
]

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom User Model
AUTH_USER_MODEL = 'logistics.CustomUser'

# Login URL
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'

SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = 1209600  # 2 weeks
SESSION_SAVE_EVERY_REQUEST = False

# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logistics.log',
        },
    },
    'root': {
        'handlers': ['file'],
        'level': 'INFO',
    },
}
