import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
SECRET_KEY = os.getenv("SECRET_KEY", "")
if len(SECRET_KEY) < 24 or SECRET_KEY == "GENERATE_SECRET_KEY":
    raise ImproperlyConfigured(
        "Set SECRET_KEY to a random, private value of at least 24 characters."
    )
ALLOWED_HOSTS = [
    s.strip() for s in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
]
CSRF_TRUSTED_ORIGINS = [
    s.strip() for s in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if s.strip()
]
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "core",
    "ordering",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
# Local (scripts/start.py): this store's data is one folder, SQLite by default.
# Hosted (Compose/Runtime): DATABASE_URL points at PostgreSQL.
LOCAL_APP = os.getenv("LOCAL_APP", "false").lower() == "true"
DATA_DIR = Path(os.getenv("DATA_DIR") or BASE_DIR.parent / "data")
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT") or DATA_DIR / "media")
# Files spool to disk; at most 12 photos, 10 MiB each, per menu edit.
DATA_UPLOAD_MAX_NUMBER_FILES = 12
SOFTWARE_DEFAULT_NAME = "Order"
SOFTWARE_CONFIG_FILE = BASE_DIR / "app-config.json"
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"
MCP_ENTRY = BASE_DIR.parent / "mcp" / "dist" / "index.js"
MCP_NAME = "order"  # server name in the mcpServers config shown to the Agent
if os.getenv("DATABASE_URL"):
    url = urlparse(os.environ["DATABASE_URL"])
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(url.path.lstrip("/")),
            "USER": unquote(url.username or ""),
            "PASSWORD": unquote(url.password or ""),
            "HOST": url.hostname or "",
            "PORT": url.port or 5432,
        }
    }
    if os.getenv("DB_SSLMODE"):
        DATABASES["default"]["OPTIONS"] = {"sslmode": os.environ["DB_SSLMODE"]}
else:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATA_DIR / "db.sqlite3",
            "OPTIONS": {
                # One writer at a time: a write transaction takes the lock when it
                # starts, so check-then-write in services cannot interleave.
                "transaction_mode": "IMMEDIATE",
                "timeout": 20,
                "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            },
            "TEST": {"NAME": DATA_DIR / "test.sqlite3"},
        }
    }
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["core.permissions.IsMember"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "EXCEPTION_HANDLER": "ordering.api_errors.exception_handler",
    # Public QR ordering writes rows without signing in.
    "DEFAULT_THROTTLE_RATES": {"login": "10/min", "ordering": "30/min"},
}
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
# This App is an Agenrena Vendor. The deployment injects its credentials; they are
# never in source, logs, API responses or the frontend. Unset means the
# Agenrena features stay off and everything else keeps working.
AGENRENA_BASE_URL = os.getenv("AGENRENA_BASE_URL", "https://api.agenrena.com").rstrip("/")
AGENRENA_VENDOR_ID = os.getenv("AGENRENA_VENDOR_ID", "")
AGENRENA_VENDOR_SECRET = os.getenv("AGENRENA_VENDOR_SECRET", "")
# Where customers open the ordering pages: table QR codes and Agent-prepared
# confirmation links. Hosted, it defaults to this site. On this computer it stays
# empty until the customer entrance is published (docs/publish.md), because a
# customer's phone cannot open 127.0.0.1.
ORDER_PUBLIC_BASE_URL = os.getenv("ORDER_PUBLIC_BASE_URL", "").rstrip("/")
if ORDER_PUBLIC_BASE_URL:
    ALLOWED_HOSTS.append(urlparse(ORDER_PUBLIC_BASE_URL).hostname)
ORDER_DRAFT_TTL_MINUTES = int(os.getenv("ORDER_DRAFT_TTL_MINUTES", "30"))
# The store's page on Agenrena, linked from every customer page ("ask the store").
AGENRENA_SHARE_BASE_URL = os.getenv("AGENRENA_SHARE_BASE_URL", "https://agenrena.com").rstrip("/")
# Enable only behind a proxy that overwrites this header (the bundled nginx does).
if os.getenv("TRUST_PROXY", "false").lower() == "true":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
