"""
Django settings for roshe_logistics project.
Roshe Logistics Management System (Web)
"""
import sys
from pathlib import Path
from decouple import AutoConfig, Csv

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Always load configuration from a .env located in the project root (BASE_DIR).
# This avoids surprises under Passenger/cPanel where the process working
# directory may not be the same as the repo root.
config = AutoConfig(search_path=BASE_DIR)

# SECURITY WARNING: keep the secret key used in production secret!
# Support both SECRET_KEY and the common hosting convention DJANGO_SECRET_KEY.
SECRET_KEY = config("DJANGO_SECRET_KEY", default="").strip()
if not SECRET_KEY:
    SECRET_KEY = config("SECRET_KEY", default="").strip()
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is not set. Create a .env file (see .env.example) or set the SECRET_KEY environment variable."
    )

# SECURITY WARNING: don't run with debug turned on in production!
# Support both DEBUG and DJANGO_DEBUG.
DEBUG = config("DJANGO_DEBUG", default="").strip()
if DEBUG == "":
    DEBUG = config("DEBUG", default=False, cast=bool)
else:
    # Accept typical 0/1 as well as true/false.
    DEBUG = str(DEBUG).strip().lower() in {"1", "true", "yes", "y", "on"}

# Seed/reset tools are for local development only. Keep disabled in production.
# Set ENABLE_SEED_TOOLS=True explicitly if you really need it.
ENABLE_SEED_TOOLS = config("ENABLE_SEED_TOOLS", default=DEBUG, cast=bool)

# Developer convenience: allow `manage.py runserver` to behave like a typical
# development setup (serving static files, detailed errors), even if a
# production-like .env has DEBUG=False.
if "runserver" in sys.argv and not DEBUG:
    DEBUG = True

# NOTE:
# In production you must set a strict ALLOWED_HOSTS list.
# cPanel commonly uses DJANGO_ALLOWED_HOSTS; accept it as an override.
_allowed_hosts_raw = config("DJANGO_ALLOWED_HOSTS", default="").strip()
if not _allowed_hosts_raw:
    _allowed_hosts_raw = config("ALLOWED_HOSTS", default="localhost,127.0.0.1").strip()

ALLOWED_HOSTS = [host.strip() for host in Csv()(_allowed_hosts_raw) if host and host.strip()]

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
    'logistics.middleware.BlockAdminForManagingDirectorMiddleware',
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

# Accept Django ENGINE strings in DB_ENGINE (common copy/paste from hosting docs).
if DB_ENGINE in {"django.db.backends.postgresql", "django.db.backends.postgres"}:
    DB_ENGINE = "postgresql"
elif DB_ENGINE == "django.db.backends.sqlite3":
    DB_ENGINE = "sqlite"


def _sqlite_databases():
    return {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': config("SQLITE_PATH", default=str(BASE_DIR / 'db.sqlite3')),
        }
    }


def _postgres_databases():
    _options = {}
    _sslmode = config("DB_SSLMODE", default="").strip()
    if _sslmode:
        # Common values: disable|allow|prefer|require|verify-ca|verify-full
        _options["sslmode"] = _sslmode

    # cPanel/shared hosts often resolve "localhost" to IPv6 ::1 first, but
    # Postgres may not be listening on IPv6. Prefer IPv4 unless the user
    # explicitly provides something else.
    _raw_host = config("DB_HOST", default="127.0.0.1")
    _host = (_raw_host or "").strip()
    if _host.lower() == "localhost":
        _host = "127.0.0.1"

    return {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config("DB_NAME", default="").strip(),
            'USER': config("DB_USER", default="").strip(),
            'PASSWORD': config("DB_PASSWORD", default=""),
            # Empty HOST means UNIX socket (valid on Linux).
            'HOST': _host,
            'PORT': config("DB_PORT", default="5432").strip(),
            'OPTIONS': _options,
        }
    }


def _postgres_is_reachable(postgres_settings: dict) -> bool:
    name = postgres_settings.get('NAME')
    user = postgres_settings.get('USER')
    password = postgres_settings.get('PASSWORD')
    host = postgres_settings.get('HOST')
    port = postgres_settings.get('PORT')

    # NOTE: host may legitimately be empty (UNIX socket).
    if not (name and user and password and port):
        return False

    # Support either psycopg (v3) or psycopg2.
    psycopg_connect = None
    try:
        import psycopg  # type: ignore

        psycopg_connect = psycopg.connect
    except Exception:
        try:
            import psycopg2  # type: ignore

            psycopg_connect = psycopg2.connect
        except Exception:
            return False

    try:
        connect_timeout = int(config("DB_CONNECT_TIMEOUT", default="3"))
    except Exception:
        connect_timeout = 3

    try:
        kwargs = {
            "dbname": name,
            "user": user,
            "password": password,
            "port": port,
            "connect_timeout": connect_timeout,
        }
        # For UNIX socket connections, omit host entirely.
        if host:
            kwargs["host"] = host

        conn = psycopg_connect(**kwargs)
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


def _management_command() -> str:
    # Typical patterns:
    #   python manage.py <cmd>
    #   manage.py <cmd>
    try:
        return sys.argv[1].strip().lower()
    except Exception:
        return ""


def _skip_db_connectivity_probe() -> bool:
    # Some management commands do not need the database to be reachable just to
    # start Django (and probing connectivity can break local workflows when
    # using a production-like .env).
    #
    # Keep this list minimal: commands here will NOT validate Postgres
    # connectivity at settings import time.
    return _management_command() in {
        "check",
        "collectstatic",
        "makemigrations",
        "migrate",
        "createsuperuser",
        "changepassword",
        "shell",
        "dbshell",
    }


if DB_ENGINE in {"postgres", "postgresql", "psql"}:
    _pg = _postgres_databases()['default']
    if _skip_db_connectivity_probe():
        DATABASES = {'default': _pg}
    elif _postgres_is_reachable(_pg):
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
                "Postgres is configured but unreachable. Fix DB_* settings and credentials, install a Postgres driver "
                "(psycopg[binary] or psycopg2-binary), or set POSTGRES_FALLBACK_TO_SQLITE=True to allow SQLite fallback."
            )
else:
    DATABASES = _sqlite_databases()

_csrf_raw = config("DJANGO_CSRF_TRUSTED_ORIGINS", default="").strip()
if not _csrf_raw:
    _csrf_raw = config("CSRF_TRUSTED_ORIGINS", default="").strip()

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in Csv()(_csrf_raw)
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
TIME_ZONE = config('DJANGO_TIME_ZONE', default='Africa/Kampala').strip() or 'Africa/Kampala'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# NOTE:
# The `logistics` app already provides its static assets under `logistics/static/`.
# Listing that same folder in STATICFILES_DIRS causes duplicate files during
# `collectstatic` (the first encountered wins, later ones are ignored).
# Only add STATICFILES_DIRS if you create a separate, non-app static folder.

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

# Email (SMTP)
# Configure these in your .env / cPanel environment variables.
# cPanel mail commonly uses SSL on port 465.
EMAIL_HOST = config('EMAIL_HOST', default='').strip()
EMAIL_PORT = config('EMAIL_PORT', default=465, cast=int)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='').strip()
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_SSL = config('EMAIL_USE_SSL', default=True, cast=bool)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=False, cast=bool)

DEFAULT_FROM_EMAIL = config(
    'DEFAULT_FROM_EMAIL',
    default=(EMAIL_HOST_USER or 'ROSHE LOGISTICS <no-reply@localhost>'),
).strip()
SERVER_EMAIL = config('SERVER_EMAIL', default=DEFAULT_FROM_EMAIL).strip() or DEFAULT_FROM_EMAIL

# If no SMTP host is configured, fall back to console backend.
EMAIL_BACKEND = config(
    'EMAIL_BACKEND',
    default=(
        'django.core.mail.backends.smtp.EmailBackend'
        if EMAIL_HOST
        else 'django.core.mail.backends.console.EmailBackend'
    ),
)
