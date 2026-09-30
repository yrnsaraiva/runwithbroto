from pathlib import Path
import os
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured
from django.templatetags.static import static
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from import_export.formats.base_formats import CSV, XLSX
import dj_database_url


IMPORT_FORMATS = [CSV, XLSX]

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Carrega variáveis do .env (na raiz do projeto, ao lado do manage.py)
load_dotenv(BASE_DIR / ".env")


def _env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _env_list(name, default=""):
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = _env_bool("DEBUG", False)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Defina a variável de ambiente SECRET_KEY.")
    SECRET_KEY = "django-insecure-dev-only"

ETICKETS_BASE_URL = os.getenv("ETICKETS_BASE_URL", "https://etk-api.up.railway.app")
ETICKETS_BEARER_TOKEN = os.getenv("ETICKETS_BEARER_TOKEN")  # ex: etk_live_...
# Segredo para validar X-ETK-Signature nos avisos da API (webhook_secret do organizador)
ETICKETS_WEBHOOK_SECRET = os.getenv("ETICKETS_WEBHOOK_SECRET", "")
ETICKETS_TIMEOUT = int(os.getenv("ETICKETS_TIMEOUT", "25"))

ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    'runwithbroto.com',
    'www.runwithbroto.com',
    '.railway.app',
    *_env_list("ALLOWED_HOSTS"),
]

CSRF_TRUSTED_ORIGINS = [
    'https://*.railway.app',
    'https://runwithbroto.com',
    'https://www.runwithbroto.com',
    'http://localhost',
    'http://127.0.0.1',
]

# Application definition

INSTALLED_APPS = [
    "unfold",  # before django.contrib.admin
    "unfold.contrib.filters",  # optional, if special filters are needed
    "unfold.contrib.forms",  # optional, if special form elements are needed
    "unfold.contrib.inlines",  # optional, if special inlines are needed
    "unfold.contrib.import_export",  # optional, if django-import-export package is used
    "unfold.contrib.guardian",  # optional, if django-guardian package is used
    "unfold.contrib.simple_history",  # optional, if django-simple-history package is used
    "unfold.contrib.location_field",  # optional, if django-location-field package is used
    "unfold.contrib.constance",  # optional, if django-constance package is used

    'django.contrib.admin',
    'django.contrib.humanize',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',

    'import_export',

    "apps.core.apps.CoreConfig",
    "apps.events.apps.EventsConfig",
    "apps.scanner.apps.ScannerConfig",
    "apps.store.apps.StoreConfig",
]

MIDDLEWARE = [
    "django.middleware.gzip.GZipMiddleware",
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
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
        'DIRS': [BASE_DIR / 'templates']
        ,
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Em produção (e localmente, se quiser) defina DATABASE_URL.
if os.getenv("DATABASE_URL"):
    DATABASES['default'] = dj_database_url.parse(
        os.environ["DATABASE_URL"], conn_max_age=600
    )
elif not DEBUG:
    # O SQLite vive no disco do contentor, que é apagado a cada deploy/restart:
    # os dados "desaparecem" e o migrate do arranque recria tudo do zero.
    # Falhar alto é melhor do que perder dados em silêncio.
    raise ImproperlyConfigured(
        "Defina DATABASE_URL (Postgres) em produção; sem ela os dados ficam "
        "num SQLite efémero e perdem-se a cada deploy."
    )


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

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

if os.getenv("REDIS_URL"):
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": os.environ["REDIS_URL"],
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            }
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Africa/Maputo'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = "/static/"

# Pasta onde você coloca seus ficheiros estáticos do projeto
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

# Pasta onde o Django vai coletar tudo no deploy (collectstatic)
STATIC_ROOT = BASE_DIR / "staticfiles"


# MEDIA FILES (uploads)

MEDIA_URL = "/media/"
MEDIA_ROOT = os.getenv("MEDIA_ROOT") or ("/app/media" if not DEBUG else BASE_DIR / "media")


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}


UNFOLD = {
    "SITE_TITLE": "Run With Broto",

    "SITE_URL": "/",

    # "SITE_LOGO": lambda request: static("logo.svg"),  # both modes, optimise for 32px height
    "SITE_LOGO": {
        "light": lambda request: static("img/logo.png"),  # light mode
        "dark": lambda request: static("img/logo.png"),  # dark mode
    },
    "SITE_SYMBOL": "speed",  # symbol from icon set
    "SHOW_HISTORY": True, # show/hide "History" button, default: True
    "SHOW_VIEW_ON_SITE": True, # show/hide "View on site" button, default: True

    "DASHBOARD_CALLBACK": "apps.core.dashboard.dashboard_callback",

    "BORDER_RADIUS": "6px",
    "COLORS": {
        "base": {
            "50": "oklch(99% 0 0)",
            "100": "oklch(96% 0 0)",
            "200": "oklch(90% 0 0)",
            "300": "oklch(80% 0 0)",
            "400": "oklch(70% 0 0)",
            "500": "oklch(55% 0 0)",
            "600": "oklch(40% 0 0)",
            "700": "oklch(30% 0 0)",
            "800": "oklch(20% 0 0)",
            "900": "oklch(12% 0 0)",
            "950": "oklch(6% 0 0)"
        },

        "primary": {
            "50": "oklch(97% 0.05 95)",
            "100": "oklch(93% 0.07 95)",
            "200": "oklch(88% 0.09 95)",
            "300": "oklch(84% 0.12 95)",
            "400": "oklch(82% 0.15 95)",
            "500": "oklch(80% 0.17 95)",
            "600": "oklch(70% 0.17 95)",
            "700": "oklch(60% 0.16 95)",
            "800": "oklch(50% 0.14 95)",
            "900": "oklch(40% 0.12 95)",
            "950": "oklch(30% 0.10 95)"
        },

        "font": {
            "subtle-light": "var(--color-base-400)",
            "subtle-dark": "var(--color-base-500)",

            "default-light": "var(--color-base-700)",
            "default-dark": "var(--color-base-300)",

            "important-light": "var(--color-base-950)",
            "important-dark": "var(--color-base-100)",

            "brand-light": "var(--color-primary-600)",
            "brand-dark": "var(--color-primary-400)"
        }
    },
    "EXTENSIONS": {
        "modeltranslation": {
            "flags": {
                "en": "🇬🇧",
            },
        },
    },
    "SIDEBAR": {
        "show_search": True,  # Search in applications and models names
        "show_all_applications": True,  # Dropdown with all applications and models
        "navigation": [
            {
                "separator": False,  # Top border
                "collapsible": False,  # Collapsible group of links
                "items": [
                    {
                        "title": _("Dashboard"),
                        "icon": "dashboard",  # Supported icon set: https://fonts.google.com/icons
                        "link": reverse_lazy("admin:index"),
                    },
                    {
                        "title": _("Users"),
                        "icon": "people",
                        "link": reverse_lazy("admin:auth_user_changelist"),
                    },
                    {
                        "title": _("Tickets"),
                        "icon": "mobile_ticket",
                        "link": reverse_lazy("admin:events_externalticket_changelist"),
                    },

                ],
            },
        ],
    },
}

# Sessão longa o bastante para o scanner ficar aberto durante um evento.
SESSION_COOKIE_AGE = 60 * 60 * 12  # 12 horas

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = _env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "3600"))
    SECURE_CONTENT_TYPE_NOSNIFF = True
