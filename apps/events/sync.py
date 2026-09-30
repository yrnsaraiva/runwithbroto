"""Sincroniza o estado local dos bilhetes com o que a API ETickets diz."""
import logging

from .etk_client import parse_datetime
from .models import ExternalTicket

logger = logging.getLogger(__name__)


def apply_api_ticket(data):
    """Atualiza o ExternalTicket local a partir do JSON de um bilhete da API.

    Só toca em campos que a API é dona (pagamento, estado, entrada, QR); os
    dados do comprador ficam como foram gravados. Devolve o bilhete ou None se
    não existir localmente.
    """
    ticket_id = data.get("id")
    if not ticket_id:
        return None
    try:
        ticket = ExternalTicket.objects.get(external_id=ticket_id)
    except ExternalTicket.DoesNotExist:
        return None

    ticket.payment_status = data.get("payment") or ticket.payment_status
    ticket.status = data.get("status") or ticket.status
    ticket.entered = bool(data.get("entered", ticket.entered))
    ticket.qr_value = data.get("qrValue") or ticket.qr_value
    ticket.checkout_url = data.get("checkoutUrl") or ticket.checkout_url
    if "expiresAt" in data:
        ticket.confirmation_deadline = parse_datetime(data.get("expiresAt"))
    ticket.external_updated_at = parse_datetime(data.get("updatedAt")) or ticket.external_updated_at
    ticket.save(update_fields=[
        "payment_status", "status", "entered", "qr_value", "checkout_url",
        "external_updated_at", "confirmation_deadline", "updated_at",
    ])
    return ticket


def ensure_local_ticket(data):
    """Devolve o ExternalTicket local do bilhete da API, criando-o se faltar
    (ex.: bilhete criado noutro sítio, ou base local perdida)."""
    ticket = apply_api_ticket(data)
    if ticket:
        return ticket
    event = data.get("event") or {}
    location = event.get("location") or {}
    return ExternalTicket.objects.create(
        external_id=data["id"],
        event_id_external=data.get("eventId") or event.get("id") or "",
        event_name=event.get("name") or "",
        event_category=event.get("category") or "",
        event_province=location.get("province") or "",
        event_location_details=location.get("details") or "",
        event_image_url=event.get("imageUrl") or "",
        event_date=parse_datetime(event.get("date")),
        price_id_external=data.get("priceId") or "",
        price_amount=data.get("amount") or 0,
        entered=bool(data.get("entered")),
        qr_value=data.get("qrValue") or "",
        status=data.get("status") or "",
        payment_status=data.get("payment") or "",
        confirmation_deadline=parse_datetime(data.get("expiresAt")),
        note=data.get("note") or "",
        buyer_phone=data.get("phone") or "",
        buyer_name=data.get("fullName") or "",
        buyer_email=data.get("email") or "",
        external_created_at=parse_datetime(data.get("createdAt")),
        external_updated_at=parse_datetime(data.get("updatedAt")),
        raw_payload=data,
    )
