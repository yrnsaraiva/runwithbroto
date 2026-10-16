"""Métricas do dashboard do admin (Unfold), calculadas sobre os bilhetes locais.

Filtros (querystring): `evento` (event_id_external, vazio = todos) e `dias`
(7, 30, 90 ou 0 = desde o início). O evento filtra tudo; o período só afecta os
gráficos ao longo do tempo.
"""

import json
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce, ExtractHour, TruncDate
from django.utils import timezone

from apps.events.models import ExternalTicket, TamanhoCamisete
from apps.scanner.models import CheckInLog

# Uma só cor para séries únicas (passo escuro do amarelo da marca: legível em
# fundo claro e escuro). Os valores exactos aparecem sempre no tooltip e nas
# tabelas.
COLOR = "#c98500"
GRID = "rgba(128,128,128,0.15)"

PERIODOS = [(7, "7 dias"), (30, "30 dias"), (90, "90 dias"), (0, "Desde o início")]

ESTADOS = [
    # (rótulo, valores de payment_status)
    ("Confirmados", ("paid", "invited")),
    ("Por confirmar", ("preregistered",)),
    ("Pagamento pendente", ("pending",)),
    ("Falhados / em revisão", ("failed", "review")),
    ("Reembolsados", ("refunded",)),
]
ESTADO_LABEL = {
    "paid": "Confirmado", "invited": "Convite", "preregistered": "Por confirmar",
    "pending": "Pagamento pendente", "failed": "Falhou", "review": "Em revisão",
    "refunded": "Reembolsado",
}
CONFIRMADOS = ("paid", "invited")
VISIVEIS = ("paid", "invited", "preregistered")   # o resto depende de outro sistema por resolver
ATIVOS = ("paid", "invited", "preregistered", "pending")   # ocupam vaga

RESULTADO_SCAN = {r.value: r.label for r in CheckInLog.Result}


def _chart(labels, data, label, *, horizontal=False, line=False):
    dataset = {"label": label, "data": data, "borderColor": COLOR, "backgroundColor": COLOR}
    if line:
        dataset.update(borderWidth=2, pointRadius=3, tension=0.25, fill=False)
    else:
        dataset.update(borderRadius=4, maxBarThickness=28)
    options = {
        "plugins": {"legend": {"display": False}},
        "scales": {
            "x": {"grid": {"display": horizontal}, "beginAtZero": True},
            "y": {"grid": {"color": GRID}, "beginAtZero": True, "ticks": {"precision": 0}},
        },
    }
    if horizontal:
        options["indexAxis"] = "y"
        options["scales"] = {
            "x": {"grid": {"color": GRID}, "beginAtZero": True, "ticks": {"precision": 0}},
            "y": {"grid": {"display": False}},
        }
    return json.dumps({"labels": labels, "datasets": [dataset]}), json.dumps(options)


def _pct(parte, todo):
    return f"{round(100 * parte / todo)}%" if todo else "—"


def _int(value):
    return f"{value:,}".replace(",", " ")


def _mzn(value):
    return f"{Decimal(value or 0):,.0f}".replace(",", " ") + " MZN"


def _hora(dt):
    return timezone.localtime(dt).strftime("%d/%m %H:%M") if dt else "—"


def _filtros(request):
    get = getattr(request, "GET", {})
    try:
        dias = int(get.get("dias", 30))
    except (TypeError, ValueError):
        dias = 30
    if dias not in dict(PERIODOS):
        dias = 30
    return (get.get("evento") or "").strip(), dias


def _serie_por_dia(tickets, desde, hoje):
    """Inscrições por dia e acumulado desde `desde` até hoje (inclusive)."""
    por_dia = dict(
        tickets.filter(dia_ref__gte=desde, dia_ref__lte=hoje)
        .values("dia_ref").annotate(n=Count("id")).values_list("dia_ref", "n")
    )
    antes = tickets.filter(dia_ref__lt=desde).count()
    labels, diario, acumulado = [], [], []
    total = antes
    dia = desde
    while dia <= hoje:
        n = por_dia.get(dia, 0)
        total += n
        labels.append(dia.strftime("%d/%m"))
        diario.append(n)
        acumulado.append(total)
        dia += timedelta(days=1)
    return labels, diario, acumulado


def dashboard_callback(request, context):
    evento_id, dias = _filtros(request)
    agora = timezone.now()
    hoje = timezone.localdate(agora)

    todos = ExternalTicket.objects.filter(payment_status__in=VISIVEIS).annotate(
        dia_ref=TruncDate(Coalesce("external_created_at", "created_at"))
    )
    tickets = todos.filter(event_id_external=evento_id) if evento_id else todos

    # ---- selector de eventos (mais recentes primeiro)
    eventos = list(
        ExternalTicket.objects.filter(payment_status__in=VISIVEIS).exclude(event_id_external="")
        .values("event_id_external", "event_name").distinct().order_by("event_name")
    )

    # ---- contagens base
    por_estado = {
        row["payment_status"]: row["n"]
        for row in tickets.values("payment_status").annotate(n=Count("id"))
    }
    total = sum(por_estado.values())

    def n(*estados):
        return sum(por_estado.get(e, 0) for e in estados)

    confirmados = n(*CONFIRMADOS)
    por_confirmar = n("preregistered")
    pendentes = n("pending")
    entradas = tickets.filter(entered=True).count()
    compradores = tickets.exclude(buyer_phone="").values("buyer_phone").distinct().count()
    pagos = tickets.filter(payment_status="paid")
    receita = pagos.aggregate(t=Sum("price_amount"))["t"] or Decimal("0")
    n_pagos_com_valor = pagos.filter(price_amount__gt=0).count()

    sete = hoje - timedelta(days=6)
    catorze = hoje - timedelta(days=13)
    ultimos_7 = tickets.filter(dia_ref__gte=sete).count()
    anteriores_7 = tickets.filter(dia_ref__gte=catorze, dia_ref__lt=sete).count()
    delta = ultimos_7 - anteriores_7

    kpis = [
        {"title": "Inscrições", "metric": _int(total),
         "footer": f"{ultimos_7} nos últimos 7 dias ({'+' if delta >= 0 else ''}{delta} vs 7 anteriores)"},
        {"title": "Confirmados", "metric": _int(confirmados),
         "footer": f"{_pct(confirmados, total)} das inscrições"},
    ]
    if por_confirmar:
        kpis.append({"title": "Por confirmar", "metric": _int(por_confirmar),
                     "footer": "pré-inscritos sem confirmação"})
    if pendentes:
        kpis.append({"title": "Pagamento pendente", "metric": _int(pendentes),
                     "footer": "reservas ainda por pagar"})
    kpis.append({"title": "Pessoas (telefones únicos)", "metric": _int(compradores),
                 "footer": f"{total / compradores:.1f} bilhetes por pessoa" if compradores else "—"})
    kpis.append({"title": "Entradas (check-in)", "metric": _int(entradas),
                 "footer": f"{_pct(entradas, confirmados)} dos confirmados"})
    if receita:
        kpis.append({"title": "Receita", "metric": _mzn(receita),
                     "footer": f"ticket médio {_mzn(receita / n_pagos_com_valor)}"
                     if n_pagos_com_valor else ""})

    # ---- gráficos ao longo do tempo
    if dias:
        desde = hoje - timedelta(days=dias - 1)
    else:
        primeiro = tickets.order_by("dia_ref").values_list("dia_ref", flat=True).first()
        desde = min(primeiro or hoje, hoje)
        desde = max(desde, hoje - timedelta(days=364))          # teto de 1 ano
    labels, diario, acumulado = _serie_por_dia(tickets, desde, hoje)
    diario_json, diario_opts = _chart(labels, diario, "Inscrições")
    acum_json, acum_opts = _chart(labels, acumulado, "Inscrições acumuladas", line=True)

    # ---- estado das inscrições
    estados = [(rotulo, n(*valores)) for rotulo, valores in ESTADOS]
    estados = [(r, v) for r, v in estados if v]
    estado_json, estado_opts = _chart(
        [r for r, _ in estados], [v for _, v in estados], "Inscrições", horizontal=True)

    # ---- camisetes (inscrições que ocupam vaga)
    camisetes = dict(
        tickets.filter(payment_status__in=ATIVOS)
        .values("tamanho_camisete").annotate(n=Count("id"))
        .values_list("tamanho_camisete", "n")
    )
    tamanhos = [(v, camisetes.get(v, 0)) for v in TamanhoCamisete.values]
    sem_tamanho = camisetes.get("", 0)
    tem_camisetes = any(v for _, v in tamanhos)
    camisete_json, camisete_opts = _chart(
        [t for t, _ in tamanhos], [v for _, v in tamanhos], "Camisetes")

    # ---- check-in
    logs = CheckInLog.objects.all()
    if evento_id:
        logs = logs.filter(ticket_external_id__in=tickets.values("external_id"))
    ok_logs = logs.filter(result=CheckInLog.Result.OK)
    por_hora = dict(
        ok_logs.annotate(h=ExtractHour("scanned_at")).values("h")
        .annotate(n=Count("id")).values_list("h", "n")
    )
    if por_hora:
        h0, h1 = min(por_hora), max(por_hora)
        horas_json, horas_opts = _chart(
            [f"{h:02d}h" for h in range(h0, h1 + 1)],
            [por_hora.get(h, 0) for h in range(h0, h1 + 1)], "Check-ins")
    else:
        horas_json = horas_opts = None
    scans = {r["result"]: r["n"] for r in logs.values("result").annotate(n=Count("id"))}
    tabela_scans = {
        "headers": ["Resultado do scan", "Tentativas"],
        "rows": [[RESULTADO_SCAN[k], _int(scans[k])] for k in RESULTADO_SCAN if scans.get(k)],
    }
    porteiros = list(
        ok_logs.exclude(scanned_by=None).values("scanned_by__username")
        .annotate(n=Count("id")).order_by("-n")[:5]
    )
    tabela_porteiros = {
        "headers": ["Porteiro", "Entradas registadas"],
        "rows": [[p["scanned_by__username"], _int(p["n"])] for p in porteiros],
    }

    # ---- resumo por evento (sempre todos os eventos)
    por_evento = (
        ExternalTicket.objects.filter(payment_status__in=VISIVEIS).values("event_name")
        .annotate(
            total=Count("id"),
            conf=Count("id", filter=Q(payment_status__in=CONFIRMADOS)),
            pre=Count("id", filter=Q(payment_status="preregistered")),
            ent=Count("id", filter=Q(entered=True)),
            rec=Sum("price_amount", filter=Q(payment_status="paid")),
        )
        .order_by("-total")
    )
    tabela_eventos = {
        "headers": ["Evento", "Inscrições", "Confirmados", "Por confirmar",
                    "Entradas", "Presença", "Receita"],
        "rows": [
            [e["event_name"] or "—", _int(e["total"]), _int(e["conf"]), _int(e["pre"]),
             _int(e["ent"]), _pct(e["ent"], e["conf"]), _mzn(e["rec"])]
            for e in por_evento
        ],
    }

    # ---- últimas inscrições
    recentes = tickets.annotate(
        quando=Coalesce("external_created_at", "created_at")
    ).order_by("-quando")[:10]
    tabela_recentes = {
        "headers": ["Participante", "Telefone", "Evento", "Estado", "Quando"],
        "rows": [
            [t.buyer_name or "—", t.buyer_phone or "—", t.event_name or "—",
             ESTADO_LABEL.get(t.payment_status.lower(), t.payment_status or "—"),
             _hora(t.external_created_at or t.created_at)]
            for t in recentes
        ],
    }

    context.update({
        "filtro_evento": evento_id,
        "filtro_dias": dias,
        "filtro_eventos": eventos,
        "filtro_periodos": PERIODOS,
        "kpis": kpis,
        "diarioChartData": diario_json, "diarioChartOptions": diario_opts,
        "acumuladoChartData": acum_json, "acumuladoChartOptions": acum_opts,
        "estadoChartData": estado_json, "estadoChartOptions": estado_opts,
        "tem_estados": bool(estados),
        "camisetesChartData": camisete_json, "camisetesChartOptions": camisete_opts,
        "tem_camisetes": tem_camisetes, "sem_tamanho": sem_tamanho,
        "horasChartData": horas_json, "horasChartOptions": horas_opts,
        "table_scans": tabela_scans, "tem_scans": bool(tabela_scans["rows"]),
        "table_porteiros": tabela_porteiros, "tem_porteiros": bool(porteiros),
        "table_eventos": tabela_eventos,
        "table_recentes": tabela_recentes,
        "atualizado_em": agora,
    })
    return context
