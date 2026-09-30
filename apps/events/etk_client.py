"""Cliente único para a API ETickets (usado pela home e pelas views de eventos)."""
import logging
from datetime import datetime

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Overrides temporários por id de evento, ex.: {"EVNT123": {"name": "Novo nome"}}
EVENT_OVERRIDES = {}


def request(method, path, json=None, timeout=None):
    """Faz o pedido à API e devolve o JSON. Regista o corpo em caso de erro HTTP."""
    token = settings.ETICKETS_BEARER_TOKEN
    if not token:
        raise requests.RequestException("ETICKETS_BEARER_TOKEN não configurado.")
    url = f"{settings.ETICKETS_BASE_URL.rstrip('/')}{path}"
    headers = {"Authorization": f"Bearer {token}"}
    if json is not None:
        headers["Content-Type"] = "application/json"
    resp = requests.request(
        method, url, headers=headers, json=json,
        timeout=timeout or settings.ETICKETS_TIMEOUT,
    )
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text
        logger.error("Erro na requisição para %s: %s — resposta: %s", url, e, detail)
        raise
    return resp.json()


def apply_event_overrides(event_data):
    overrides = EVENT_OVERRIDES.get(str(event_data.get("id")))
    if overrides:
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(event_data.get(key), dict):
                event_data[key].update(value)
            else:
                event_data[key] = value
    return event_data


def parse_datetime(value):
    """ISO 8601 (com Z ou offset) -> datetime aware; None se inválido."""
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        from django.utils import timezone
        dt = timezone.make_aware(dt, timezone.utc)
    return dt


def get_events(upcoming=False):
    path = "/back/borrow/external/events" + ("?upcoming=true" if upcoming else "")
    data = request("GET", path)
    return [apply_event_overrides(e) for e in data.get("data", [])]


def get_event(event_id):
    data = request("GET", f"/back/borrow/external/events/{event_id}")
    return apply_event_overrides(data.get("data", {}))


def create_ticket(payload):
    return request("POST", "/back/borrow/external/tickets", json=payload)


def create_invites(payload):
    """Emite convites gratuitos (ocupam vaga; nascem `invited`). Devolve a lista de bilhetes."""
    return request("POST", "/back/borrow/external/invites", json=payload).get("data", [])


def get_ticket(ticket_id):
    """Sonda o estado atual de um bilhete (pagamento, entrada...)."""
    return request("GET", f"/back/borrow/external/tickets/{ticket_id}").get("data", {})


def list_tickets(since=None, event_id=None, payment=None, phone=None):
    """Bilhetes da chave; `since` (ISO 8601) devolve só os alterados desde então.
    `phone` devolve todos os bilhetes desse telefone (pode haver vários)."""
    from urllib.parse import urlencode
    params = {k: v for k, v in
              {"since": since, "eventId": event_id, "payment": payment,
               "phone": phone}.items() if v}
    path = "/back/borrow/external/tickets" + (f"?{urlencode(params)}" if params else "")
    return request("GET", path).get("data", [])


def confirm_ticket(ticket_id, phone):
    """Confirma a presença de uma pré-inscrição (a API exige o telefone do bilhete)."""
    return request("POST", f"/back/borrow/external/tickets/{ticket_id}/confirm",
                   json={"phone": phone}).get("data", {})


def check_in(qr_value):
    """Check-in autoritativo na API (valida a assinatura do QR)."""
    data = request("POST", "/back/borrow/external/tickets/check-in", json={"qrValue": qr_value})
    return data.get("message", ""), data.get("data") or {}
