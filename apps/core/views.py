import json
import logging
from datetime import datetime, timezone as dt_timezone, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.core.cache import cache
from django.db.models import Count, Sum, Q
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone

from apps.events import etk_client
from apps.events.etk_client import parse_datetime
from apps.events.models import ExternalTicket

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

def dashboard_callback(request, context):
    """
    Callback para o dashboard do admin.
    Gera KPIs, gráficos e tabela de tickets por evento.
    """
    tickets = ExternalTicket.objects.all()
    hoje = timezone.now()
    ultimos_7_dias = hoje - timedelta(days=6)

    tickets_pagos = tickets.filter(payment_status="paid", entered=False).count()
    total_eventos = tickets.values("event_id_external").distinct().count()
    receita_total = (
        tickets.filter(payment_status="paid")
        .aggregate(total=Sum("price_amount"))
        .get("total") or Decimal("0.00")
    )

    tickets_por_dia_qs = (
        tickets.filter(
            external_created_at__date__gte=ultimos_7_dias.date(),
            external_created_at__date__lte=hoje.date(),
        )
        .annotate(dia=TruncDate("external_created_at"))
        .values("dia")
        .annotate(total=Count("id"))
        .order_by("dia")
    )
    tickets_por_dia_map = {item["dia"]: item["total"] for item in tickets_por_dia_qs}

    vendas_por_dia_qs = (
        tickets.filter(
            payment_status="paid",
            external_created_at__date__gte=ultimos_7_dias.date(),
            external_created_at__date__lte=hoje.date(),
        )
        .annotate(dia=TruncDate("external_created_at"))
        .values("dia")
        .annotate(total=Sum("price_amount"))
        .order_by("dia")
    )
    vendas_por_dia_map = {item["dia"]: float(item["total"] or 0) for item in vendas_por_dia_qs}

    labels_7_dias, dados_tickets_7_dias, dados_vendas_7_dias = [], [], []
    for i in range(7):
        dia = ultimos_7_dias.date() + timedelta(days=i)
        labels_7_dias.append(dia.strftime("%d/%m"))
        dados_tickets_7_dias.append(tickets_por_dia_map.get(dia, 0))
        dados_vendas_7_dias.append(vendas_por_dia_map.get(dia, 0))

    tickets_por_evento = list(
        tickets.values("event_name")
        .annotate(
            total=Count("id"),
            pagos=Count("id", filter=Q(payment_status="paid")),
            entrados=Count("id", filter=Q(entered=True)),
            receita=Sum("price_amount", filter=Q(payment_status="paid")),
        )
        .order_by("-total")
    )

    context.update({
        "kpis": [
            {"title": "Eventos", "metric": total_eventos},
            {"title": "Tickets Pagos", "metric": tickets_pagos},
            {"title": "Receita Total", "metric": f"{receita_total:.2f} MZN"},
        ],
        "pedidosChartData": json.dumps({
            "labels": labels_7_dias,
            "datasets": [{"label": "Tickets", "data": dados_tickets_7_dias}],
        }),
        "vendasChartData": json.dumps({
            "labels": labels_7_dias,
            "datasets": [{"label": "Vendas (MZN)", "data": dados_vendas_7_dias}],
        }),
        "table_tickets_por_evento": {
            "headers": ["Evento", "Tickets Pagos", "Receita"],
            "rows": [
                [item["event_name"], item["pagos"], f'{item["receita"] or Decimal("0.00"):.2f} MZN']
                for item in tickets_por_evento
            ],
        },
    })

    return context


def not_found(request, exception):
    return render(request, 'core/not_found.html', status=404)