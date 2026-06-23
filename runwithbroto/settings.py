from pathlib import Path
import os
from dotenv import load_dotenv
import dj_database_url
from django.templatetags.static import static
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from import_export.formats.base_formats import CSV, XLSX


IMPORT_FORMATS = [CSV, XLSX]

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Carrega variáveis do .env (na raiz do projeto, ao lado do manage.py)
load_dotenv(BASE_DIR / ".env")


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-m@98y4fg_3j_c-_z7kq(fyqjzagr63e1g3^use=y@!vn^r-ce!'

ETICKETS_BASE_URL = os.getenv("ETICKETS_BASE_URL", "https://eticketsmz.site")
ETICKETS_BEARER_TOKEN = os.getenv("ETICKETS_BEARER_TOKEN")  # ex: etk_live_...
ETICKETS_TIMEOUT = int(os.getenv("ETICKETS_TIMEOUT", "15"))

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    'runwithbroto.com',
    'www.runwithbroto.com',
    'nqhgstr.up.railway.app',  # domínio do Railway
    '.railway.app',  # permite qualquer subdomínio do Railway
    '*'
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
    "apps.members.apps.MembersConfig",
    "apps.scanner.apps.ScannerConfig"
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
]

ROOT_URLCONF = 'runwithbroto.urls'

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

WSGI_APPLICATION = 'runwithbroto.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

POSTGRES_LOCALLY = True
if not DEBUG or POSTGRES_LOCALLY:
    DATABASES['default'] = dj_database_url.parse(
        'postgresql://postgres:WQKNszCbpLWwdnSARMgwulCUNrXsoOpi@tramway.proxy.rlwy.net:50885/railway')


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


CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

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
MEDIA_ROOT = BASE_DIR / "media"


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

    "DASHBOARD_CALLBACK": "apps.core.views.dashboard_callback",

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
                    {
                        "title": _("Interesse Membros Fundadores"),
                        "icon": "assignment",
                        "link": reverse_lazy("admin:members_interessemembrofundador_changelist"),
                    },
                    {
                        "title": _("Membership Plans"),
                        "icon": "crown",
                        "link": reverse_lazy("admin:members_plano_changelist"),
                    },
                    {
                        "title": _("Membership"),
                        "icon": "card_membership",
                        "link": reverse_lazy("admin:members_assinatura_changelist"),
                    },

                ],
            },
        ],
    },
}

SESSION_COOKIE_AGE = 1800  # 30 minutos

SESSION_SAVE_EVERY_REQUEST = True