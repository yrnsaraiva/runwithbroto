import json
import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.db.models import Count, Q

from apps.events.models import ExternalTicket
from .models import CheckInLog

logger = logging.getLogger(__name__)


@staff_member_required
def scanner_view(request):
    """Interface principal do scanner."""
    return render(request, "scanner/scanner.html")


@staff_member_required
@require_http_methods(["POST"])
def validate_ticket(request):
    """
    Valida o QR lido e executa o check-in.

    Body JSON: { "qr_value": "RWB|<external_id>" }

    Retorna:
        status : ok | already_entered | not_paid | not_found | invalid_qr
        message: texto amigável
        ticket : dados do ticket (quando encontrado)
    """
    try:
        body = json.loads(request.body)
        qr_value = (body.get("qr_value") or "").strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"status": "error", "message": "Payload inválido."}, status=400)

    if not qr_value:
        return JsonResponse({"status": "error", "message": "QR vazio."}, status=400)

    # ── Validar prefixo ──────────────────────────────────
    if not qr_value.startswith("RWB|"):
        _log(request, qr_value, "", CheckInLog.Result.INVALID_QR)
        return JsonResponse({
            "status": "invalid_qr",
            "message": "QR code não reconhecido. Não é um bilhete válido.",
        })

    external_id = qr_value[4:].strip()

    # ── Buscar ticket + check-in atómico ─────────────────
    # select_for_update serializa scanners concorrentes no mesmo bilhete.
    with transaction.atomic():
        try:
            ticket = ExternalTicket.objects.select_for_update().get(external_id=external_id)
        except ExternalTicket.DoesNotExist:
            ticket = None

        if ticket is None:
            result, status, message = CheckInLog.Result.NOT_FOUND, "not_found", f"Bilhete '{external_id}' não encontrado."
        elif ticket.payment_status.lower() != "paid":
            result, status = CheckInLog.Result.NOT_PAID, "not_paid"
            message = f"Pagamento não confirmado (status: {ticket.payment_status})."
        elif ticket.entered:
            result, status = CheckInLog.Result.ALREADY_ENTERED, "already_entered"
            message = "Este bilhete já foi utilizado para entrada."
        else:
            ticket.entered = True
            ticket.save(update_fields=["entered", "updated_at"])
            result, status, message = CheckInLog.Result.OK, "ok", "Entrada autorizada!"

    _log(request, qr_value, external_id, result)
    if status == "ok":
        logger.info("check-in OK | %s | %s | staff=%s", external_id, ticket.event_name, request.user)

    response = {"status": status, "message": message}
    if ticket is not None:
        response["ticket"] = _ticket_info(ticket)
    return JsonResponse(response)


@staff_member_required
@require_http_methods(["GET"])
def stats_view(request):
    """Estatísticas de check-in, com filtro opcional por evento."""
    event_name = request.GET.get("event_name", "").strip()

    qs = ExternalTicket.objects.filter(payment_status__iexact="paid")
    if event_name:
        qs = qs.filter(event_name=event_name)

    total_paid    = qs.count()
    total_entered = qs.filter(entered=True).count()

    events = (
        ExternalTicket.objects
        .filter(payment_status__iexact="paid")
        .values_list("event_name", flat=True)
        .distinct()
        .order_by("event_name")
    )

    return JsonResponse({
        "total_paid":    total_paid,
        "total_entered": total_entered,
        "total_pending": total_paid - total_entered,
        "events":        list(events),
        "event_filter":  event_name,
    })


@staff_member_required
@require_http_methods(["GET"])
def log_view(request):
    """Últimos 50 check-ins para exibir no painel."""
    event_name = request.GET.get("event_name", "").strip()

    qs = CheckInLog.objects.select_related("scanned_by")
    if event_name:
        # Filtra pelo evento via ticket id (join indireto via external_id)
        ids = ExternalTicket.objects.filter(
            event_name=event_name
        ).values_list("external_id", flat=True)
        qs = qs.filter(ticket_external_id__in=ids)

    logs = [
        {
            "ticket_id": log.ticket_external_id,
            "result":    log.result,
            "result_display": log.get_result_display(),
            "scanned_by": log.scanned_by.username if log.scanned_by else "—",
            "scanned_at": log.scanned_at.strftime("%H:%M:%S"),
        }
        for log in qs[:50]
    ]

    return JsonResponse({"logs": logs})


# ── helpers ────────────────────────────────────────────────────────────────────

def _ticket_info(ticket) -> dict:
    return {
        "external_id":      ticket.external_id,
        "buyer_name":       ticket.buyer_name or "—",
        "buyer_phone":      ticket.buyer_phone or "—",
        "event_name":       ticket.event_name or "—",
        "event_date":       ticket.event_date.strftime("%d/%m/%Y %H:%M") if ticket.event_date else "—",
        "payment_status":   ticket.payment_status,
        "entered":          ticket.entered,
        "price_amount":     str(ticket.price_amount),
        "tamanho_camisete": ticket.get_tamanho_camisete_display() if ticket.tamanho_camisete else "—",
    }


def _log(request, raw_qr: str, external_id: str, result: str):
    try:
        CheckInLog.objects.create(
            ticket_external_id=external_id,
            result=result,
            scanned_by=request.user if request.user.is_authenticated else None,
            raw_qr=raw_qr,
        )
    except Exception as e:
        logger.warning("Erro ao gravar CheckInLog: %s", e)