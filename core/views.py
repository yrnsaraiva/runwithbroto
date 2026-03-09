import json

from django.shortcuts import render
from decimal import Decimal
from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import timedelta
from django.db.models.functions import TruncDate

from events.models import ExternalTicket


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

    # Tickets por província do comprador
    mapa_provincias = dict(ExternalTicket._meta.get_field("buyer_province").choices)

    tickets_por_provincia_qs = (
        tickets.exclude(buyer_province="")
        .values("buyer_province")
        .annotate(total=Count("id"),
                  receita=Sum("price_amount", filter=Q(payment_status="paid")),
                  )
        .order_by("-total")
    )

    tickets_por_provincia = [
        {
            "provincia": mapa_provincias.get(item["buyer_province"], item["buyer_province"]),
            "total": item["total"],
            "receita": item["receita"] or Decimal("0.00"),
        }
        for item in tickets_por_provincia_qs
    ]

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
    table_tickets_por_provincia = {
        "headers": ["Província", "Tickets Pagos", "Receita"],
        "rows": [
            [
                item["provincia"],
                item["total"],
                f'{item["receita"] or Decimal("0.00"):.2f} MZN',
            ]
            for item in tickets_por_provincia
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
        "table_tickets_por_provincia": table_tickets_por_provincia,
    })

    return context