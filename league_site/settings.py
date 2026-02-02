from pathlib import Path
import os

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# =========================
# Core
# =========================
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

# ALLOWED_HOSTS: local + env + Render hostname
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]
RENDER_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_HOST:
    ALLOWED_HOSTS.append(RENDER_HOST)

# =========================
# Apps
# =========================
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "league.apps.LeagueConfig","cloudinary", "cloudinary_storage"
]

# =========================
# Middleware
# =========================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serve static in production
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "league_site.urls"

# =========================
# Templates
# =========================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],  # templates inside app
        "APP_DIRS": True,
        "OPTIONS": {
            # Custom template filters (e.g. `media_src`) used across many templates.
            # Register them globally so templates don't need `{% load dict_extras %}`.
            "builtins": [
                "league.templatetags.dict_extras",
            ],
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },

]

WSGI_APPLICATION = "league_site.wsgi.application"

# =========================
# Database
# =========================
# - Locally: sqlite works (no DATABASE_URL set)
# - On Render: set DATABASE_URL to your Postgres URL
DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=600,
    )
}

# =========================
# Auth
# =========================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# =========================
# i18n / tz
# =========================
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True

# =========================
# Static / Media
# =========================
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"



# =========================
# Storage (Cloudinary on Render; local fallback)
# =========================
# We enable Cloudinary only when CLOUDINARY_URL is provided in the environment.
# This prevents admin image uploads from crashing when the variable is missing/misnamed.
USE_CLOUDINARY = bool(os.environ.get("CLOUDINARY_URL"))

if USE_CLOUDINARY:
    STORAGES = {
        "default": {"BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.MediaCloudinaryStorage"
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
ENABLE_SCOPE_REBUILD_ON_SAVE = False  # do NOT rebuild heavy standings on every admin save

# =========================
# Performance switches
# =========================
# Turn OFF all automatic recalculation work (fixture totals, standings rebuild triggers, etc.).
# Run it manually when you want via:
#   python manage.py recalculate_latest
XL_ENABLE_AUTO_UPDATES = os.environ.get("XL_ENABLE_AUTO_UPDATES", "0") in ("1", "true", "True")

# Optional: if you ever want automatic scope rebuilds on transfer saves, set this to 1.
XL_REBUILD_SCOPES_ON_TRANSFER = os.environ.get("XL_REBUILD_SCOPES_ON_TRANSFER", "0") in ("1", "true", "True")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# =========================
# Production security (safe defaults)
# =========================
# If you later add a custom domain, set DJANGO_CSRF_TRUSTED_ORIGINS accordingly:
# e.g. https://yourdomain.com, https://www.yourdomain.com
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

if not DEBUG:
    # Behind Render proxy
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_REFERRER_POLICY = "same-origin"
