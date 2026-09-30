import json
import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.db.models import Count, Q

from apps.events import etk_client
from apps.events.models import ExternalTicket
from apps.events.sync import apply_api_ticket
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

    # ── QR assinado pela API (TCKT…|assinatura): validação autoritativa lá ──
    if not qr_value.startswith("RWB|"):
        return _validate_via_api(request, qr_value)

    # ── QR antigo (RWB|<id>): bilhetes emitidos antes da API assinar QR ──
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


_API_RESULT = {
    "ok": CheckInLog.Result.OK,
    "already_entered": CheckInLog.Result.ALREADY_ENTERED,
    "not_paid": CheckInLog.Result.NOT_PAID,
    "not_found": CheckInLog.Result.NOT_FOUND,
    "invalid_qr": CheckInLog.Result.INVALID_QR,
}


def _validate_via_api(request, qr_value):
    """Check-in na API (verifica a assinatura do QR e evita entradas duplicadas
    entre dispositivos) e espelha o resultado na base local."""
    try:
        message, data = etk_client.check_in(qr_value)
    except Exception as exc:
        logger.error("check-in na API falhou: %s", exc)
        return JsonResponse({
            "status": "error",
            "message": "Sem ligação à API de bilhetes. Tente novamente.",
        }, status=502)

    status = data.get("result") or "invalid_qr"
    api_ticket = data.get("ticket") or {}
    external_id = api_ticket.get("id", "")
    _log(request, qr_value, external_id, _API_RESULT.get(status, CheckInLog.Result.INVALID_QR))

    response = {"status": status, "message": message}
    if api_ticket:
        local = apply_api_ticket(api_ticket)
        response["ticket"] = _ticket_info(local) if local else {
            "external_id": external_id,
            "buyer_name": api_ticket.get("fullName") or "—",
            "buyer_phone": api_ticket.get("phone") or "—",
            "event_name": (api_ticket.get("event") or {}).get("name") or "—",
            "event_date": "—",
            "payment_status": api_ticket.get("payment", ""),
            "entered": bool(api_ticket.get("entered")),
            "price_amount": str(api_ticket.get("amount", 0)),
            "tamanho_camisete": "—",
        }
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