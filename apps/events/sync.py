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
    ticket.external_updated_at = parse_datetime(data.get("updatedAt")) or ticket.external_updated_at
    ticket.save(update_fields=[
        "payment_status", "status", "entered", "qr_value", "checkout_url",
        "external_updated_at", "updated_at",
    ])
    return ticket
