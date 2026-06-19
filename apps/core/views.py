import json
import requests
from datetime import datetime
from django.shortcuts import render
from decimal import Decimal
from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import timezone as dt_timezone
from datetime import timedelta
from django.db.models.functions import TruncDate
import logging

from apps.events.models import ExternalTicket

logger = logging.getLogger(__name__)


def home(request):
    url = "https://eticketsmz.site/borrow/external/events"

    headers = {
        "Authorization": "Bearer etk_live_3SZPEA7FNCZAdqjIaBIIbI7j"
    }

    events = []

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        for e in data.get("data", []):

            event_id = e.get("id")

            # ❌ elimina eventos sem ID (causa do teu erro)
            if not event_id:
                continue

            # parse da data
            start_at = None
            if e.get("date"):
                try:
                    start_at = datetime.fromisoformat(
                        e["date"].replace("Z", "+00:00")
                    )
                except Exception:
                    start_at = None

            events.append({
                "event_id": event_id,
                "title": e.get("name"),
                "description": e.get("description") or "",
                "slug": event_id,
                "city": (e.get("location") or {}).get("province"),
                "meeting_point": (e.get("location") or {}).get("details"),
                "event_type": e.get("category"),
                "confirmed_count": e.get("totalTicketsPurchased", 0),
                "start_at": start_at,
                "image": e.get("imageUrl")
            })

    except Exception as e:
        logger.error(f"Erro ao carregar eventos: {e}")
        events = []

    # DEBUG (podes remover em produção)
    logger.warning(f"TOTAL EVENTS: {len(events)}")
    for ev in events:
        logger.warning(f"{ev['title']} | {ev['event_id']} | {ev['start_at']}")

    now = timezone.now().astimezone(dt_timezone.utc)

    # filtrar apenas eventos futuros válidos
    future_events = [
        e for e in events
        if e.get("event_id")
        and e.get("start_at")
        and e["start_at"].astimezone(dt_timezone.utc) >= now
    ]

    logger.warning(f"FUTURE EVENTS: {len(future_events)}")

    # evento mais próximo
    next_event = min(
        future_events,
        key=lambda x: x["start_at"],
        default=None
    )

    return render(request, "core/index.html", {
        "events": events,
        "next_event": next_event,
    })


def contact(request):
    return render(request, "core/contact.html")


def our_story(request):
    return render(request, "core/our-story.html")


def dashboard_callback(request, context):
    tickets = ExternalTicket.objects.all()
    hoje = timezone.now()
    ultimos_7_dias = hoje - timedelta(days=6)

    # KPIs
    tickets_pagos = tickets.filter(payment_status="paid").count()
    total_eventos = tickets.values("event_id_external").distinct().count()

    receita_total = (
        tickets.filter(payment_status="paid")
        .aggregate(total=Sum("price_amount"))
        .get("total")
        or Decimal("0.00")
    )

    # Gráfico: tickets por dia
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

    tickets_por_dia_map = {
        item["dia"]: item["total"]
        for item in tickets_por_dia_qs
    }

    labels_7_dias = []
    dados_tickets_7_dias = []

    for i in range(7):
        dia = ultimos_7_dias.date() + timedelta(days=i)
        labels_7_dias.append(dia.strftime("%d/%m"))
        dados_tickets_7_dias.append(tickets_por_dia_map.get(dia, 0))

    pedidosChartData = json.dumps(
        {
            "labels": labels_7_dias,
            "datasets": [
                {
                    "label": "Tickets",
                    "data": dados_tickets_7_dias,
                }
            ],
        }
    )

    # Gráfico: vendas por dia
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

    vendas_por_dia_map = {
        item["dia"]: float(item["total"] or 0)
        for item in vendas_por_dia_qs
    }

    dados_vendas_7_dias = []
    for i in range(7):
        dia = ultimos_7_dias.date() + timedelta(days=i)
        dados_vendas_7_dias.append(vendas_por_dia_map.get(dia, 0))

    vendasChartData = json.dumps(
        {
            "labels": labels_7_dias,
            "datasets": [
                {
                    "label": "Vendas (MZN)",
                    "data": dados_vendas_7_dias,
                }
            ],
        }
    )


    # Tickets por evento
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

    # Tabela-resumo no formato simples para usar no template
    table_tickets_por_evento = {
        "headers": ["Evento", "Tickets Pagos", "Receita"],
        "rows": [
            [
                item["event_name"],
                item["pagos"],
                f'{item["receita"] or Decimal("0.00"):.2f} MZN',
            ]
            for item in tickets_por_evento
        ],
    }

    context.update({
        "kpis": [
            {"title": "Eventos", "metric": total_eventos},
            {"title": "Tickets Pagos", "metric": tickets_pagos},
            {"title": "Receita Total", "metric": f"{receita_total:.2f} MZN"},
        ],
        "pedidosChartData": pedidosChartData,
        "vendasChartData": vendasChartData,
        "table_tickets_por_evento": table_tickets_por_evento,
    })

    return context