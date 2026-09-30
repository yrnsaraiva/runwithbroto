import logging
from datetime import timezone as dt_timezone

from django.core.cache import cache
from django.shortcuts import render
from django.utils import timezone

from apps.events import etk_client
from apps.events.etk_client import parse_datetime

logger = logging.getLogger(__name__)

CACHE_HOME_KEY = "core:home_events"
CACHE_HOME_TTL = 60 * 5  # 5 minutos


def _build_event_summary(event_data):
    """
    Constrói um dicionário resumido para listagem, já com overrides aplicados.
    """
    start_at = parse_datetime(event_data.get("date"))
    return {
        "event_id": event_data.get("id"),
        "title": event_data.get("name"),
        "description": event_data.get("description") or "",
        "slug": event_data.get("id"),
        "city": (event_data.get("location") or {}).get("province"),
        "meeting_point": (event_data.get("location") or {}).get("details"),
        "event_type": event_data.get("category"),
        "confirmed_count": event_data.get("totalTicketsPurchased", 0),
        "start_at": start_at,
        "image": event_data.get("imageUrl"),
    }

# =============================================================================
# VIEWS
# =============================================================================


def _fetch_home_events() -> tuple[list, list]:
    """
    Retorna (events, future_events) com cache.
    Aplica os overrides definidos em EVENT_OVERRIDES.
    """
    cached = cache.get(CACHE_HOME_KEY)
    if cached is not None:
        return cached

    events = []
    try:
        for e in etk_client.get_events():
            events.append(_build_event_summary(e))
    except Exception as e:
        logger.warning(f"Erro ao carregar eventos (home): {e}")
        return [], []  # não cacheia a falha

    now = timezone.now().astimezone(dt_timezone.utc)
    future_events = [
        e for e in events
        if e.get("start_at")
        and e["start_at"].astimezone(dt_timezone.utc) >= now
    ]

    result = (events, future_events)
    cache.set(CACHE_HOME_KEY, result, CACHE_HOME_TTL)
    return result


def home(request):
    """Página inicial com lista de eventos e próximo evento."""
    events, future_events = _fetch_home_events()

    next_event = min(
        future_events,
        key=lambda x: x["start_at"],
        default=None,
    )

    return render(request, "core/index.html", {
        "events": events,
        "next_event": next_event,
    })


def contact(request):
    """Página de contacto."""
    return render(request, "core/contact.html")


def our_story(request):
    """Página 'A Nossa História'."""
    return render(request, "core/our-story.html")


# =============================================================================
# DASHBOARD (ADMIN)
# =============================================================================

def not_found(request, exception):
    return render(request, 'core/not_found.html', status=404)