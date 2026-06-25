# runwithbroto/sitemaps.py
from django.contrib.sitemaps import Sitemap
from django.urls import reverse
import logging

logger = logging.getLogger(__name__)


class MeuSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.5

    def items(self):
        # Usando o namespace do app
        return [
            'core:home',  # Namespace:home
            'core:about',
            'core:contact',
        ]

    def location(self, item):
        try:
            return reverse(item)
        except Exception as e:
            logger.error(f"Erro ao gerar URL para {item}: {e}")
            return '/'