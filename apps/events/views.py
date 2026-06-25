import os
import re
import logging
from datetime import datetime
from types import SimpleNamespace

import requests
from django.contrib import messages
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .models import ExternalTicket, TamanhoCamisete
from .pdf import build_external_ticket_pdf

logger = logging.getLogger(__name__)

ETK_BASE = "https://eticketsmz.site"
ETK_TOKEN = os.environ.get("ETK_TOKEN", "etk_live_3SZPEA7FNCZAdqjIaBIIbI7j")
TIMEOUT_READ = 10
TIMEOUT_WRITE = 30
CACHE_EVENTS_KEY = "events:list"
CACHE_EVENTS_TTL = 60 * 5  # 5 minutos


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _auth_headers():
    return {"Authorization": f"Bearer {ETK_TOKEN}"}


def _parse_iso(raw: str):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _fetch_events_from_api() -> list:
    url = f"{ETK_BASE}/borrow/external/events"
    try:
        response = requests.get(url, headers=_auth_headers(), timeout=TIMEOUT_READ)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.warning(f"Erro ao carregar eventos: {e}")
        return []

    events = []
    for e in data.get("data", []):
        events.append({
            "event_id": e.get("id"),
            "title": e.get("name"),
            "slug": e.get("id"),
            "city": (e.get("location") or {}).get("province"),
            "meeting_point": (e.get("location") or {}).get("details"),
            "event_type": e.get("category"),
            "confirmed_count": e.get("totalTicketsPurchased", 0),
            "start_at": _parse_iso(e.get("date")),
            "image": e.get("imageUrl"),
        })
    return events


# ─────────────────────────────────────────────
# VIEWS
# ─────────────────────────────────────────────

@require_http_methods(["GET"])
def event_list(request):
    events = cache.get(CACHE_EVENTS_KEY)
    if events is None:
        events = _fetch_events_from_api()
        cache.set(CACHE_EVENTS_KEY, events, CACHE_EVENTS_TTL)

    return render(request, "events/agenda.html", {"events": events})


@require_http_methods(["GET"])
def event_detail(request, event_id):
    url = f"{ETK_BASE}/borrow/external/events/{event_id}"

    try:
        resp = requests.get(url, headers=_auth_headers(), timeout=TIMEOUT_READ)
    except requests.RequestException:
        raise Http404("Serviço indisponível")

    if resp.status_code == 404:
        raise Http404("Evento não encontrado")
    if not resp.ok:
        raise Http404(f"Erro ao carregar evento (status {resp.status_code})")

    payload = resp.json()
    e = payload.get("data") if isinstance(payload, dict) else payload
    if not e:
        raise Http404("Evento inválido")

    prices = e.get("prices") or []
    first_price = prices[0] if prices else None
    amount = first_price.get("amount") if first_price else None

    event = {
        "id": e.get("id"),
        "title": e.get("name"),
        "description": e.get("description") or "",
        "city": (e.get("location") or {}).get("province") or "",
        "meeting_point": (e.get("location") or {}).get("details") or "",
        "start_at": _parse_iso(e.get("date")),
        "ticket_price_display": f"{amount} MTn" if amount is not None else "—",
        "image_url": e.get("imageUrl"),
        "category": e.get("category"),
        "confirmed_count": e.get("totalTicketsPurchased") or 0,
    }

    return render(request, "events/event_detail.html", {"event": event})


@require_http_methods(["GET", "POST"])
def register_form(request, event_id: str):
    event_url = f"{ETK_BASE}/borrow/external/events/{event_id}"
    ticket_url = f"{ETK_BASE}/borrow/external/tickets"

    # 1) Buscar evento
    try:
        resp = requests.get(event_url, headers=_auth_headers(), timeout=TIMEOUT_READ)
    except requests.RequestException:
        messages.error(request, "Serviço indisponível. Tente novamente em instantes.")
        return redirect("events:event_list")

    if resp.status_code == 404:
        raise Http404("Evento não encontrado")
    if not resp.ok:
        messages.error(request, "Não foi possível carregar o evento.")
        return redirect("events:event_list")

    payload = resp.json()
    e = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(e, list):
        e = e[0] if e else None
    if not isinstance(e, dict) or not e:
        messages.error(request, "Evento inválido.")
        return redirect("events:event_list")

    # 2) Preço ativo
    prices = e.get("prices") or []
    price_id = next(
        (p.get("id") for p in prices if (p.get("status") or "").lower() == "active"),
        None
    )
    chosen_price = next((p for p in prices if p.get("id") == price_id), None) or (prices[0] if prices else None)
    amount = chosen_price.get("amount") if chosen_price else None

    category = e.get("category") or ""
    event = {
        "id": e.get("id"),
        "slug": e.get("id"),
        "eventId": e.get("id"),
        "title": e.get("name"),
        "description": e.get("description") or "",
        "city": (e.get("location") or {}).get("province") or "",
        "meeting_point": (e.get("location") or {}).get("details") or "",
        "start_at": _parse_iso(e.get("date")),
        "poster_url": e.get("imageUrl") or "",
        "image_url": e.get("imageUrl") or "",
        "get_event_type_display": category.replace("_", " ").title() if category else "—",
        "ticket_price_display": f"{amount} MTn" if amount is not None else "—",
        "priceId": price_id,
        "confirmed_count": e.get("totalTicketsPurchased") or 0,
    }
    tamanhos = TamanhoCamisete.choices

    if request.method == "GET":
        return render(request, "events/register.html", {"event": event, "tamanhos": tamanhos})

    # 3) POST — validar dados
    phone = re.sub(r"\D", "", (request.POST.get("phone") or "").strip())
    full_name = (request.POST.get("full_name") or "").strip()
    buyer_email = (request.POST.get("email") or "").strip()
    tamanho_camisete = (request.POST.get("tamanho_camisete") or "").strip()
    payment = (request.POST.get("payment") or "").strip()

    if not phone.startswith("258"):
        phone = f"258{phone}"

    if not re.fullmatch(r"258\d{9}", phone):
        messages.error(request, "Número inválido. Use 84/85/86/87 + 7 dígitos.")
        return render(request, "events/register.html", {"event": event, "tamanhos": tamanhos}, status=400)

    if not price_id:
        messages.error(request, "Este evento não tem preço ativo.")
        return render(request, "events/register.html", {"event": event, "tamanhos": tamanhos}, status=400)

    # 4) Enviar compra
    body = {"priceId": price_id, "eventId": event_id, "phone": phone}
    if full_name:
        body["fullName"] = full_name
    if buyer_email:
        body["email"] = buyer_email
    if payment:
        body["paymentMethod"] = payment

    api_headers = {
        "Content-Type": "application/json",
        **_auth_headers(),
    }

    try:
        pay_resp = requests.post(ticket_url, headers=api_headers, json=body, timeout=TIMEOUT_WRITE)
    except requests.RequestException:
        messages.error(request, "Não foi possível processar o pagamento. Tente novamente.")
        return render(request, "events/register.html", {"event": event, "tamanhos": tamanhos}, status=502)

    try:
        pay_data = pay_resp.json()
    except ValueError:
        pay_data = None

    if pay_resp.ok and isinstance(pay_data, dict):
        if (
            pay_data.get("status") == "success"
            and pay_data.get("message") == "Ticket created successfully"
        ):
            ticket_data = pay_data.get("data") or {}
            event_data = ticket_data.get("event") or {}
            location_data = event_data.get("location") or {}
            price_data = ticket_data.get("price") or {}

            ExternalTicket.objects.update_or_create(
                external_id=ticket_data.get("id"),
                defaults={
                    "event_id_external": ticket_data.get("eventId"),
                    "event_name": event_data.get("name") or "",
                    "event_category": event_data.get("category") or "",
                    "event_province": location_data.get("province") or "",
                    "event_location_details": location_data.get("details") or "",
                    "event_image_url": event_data.get("imageUrl") or "",
                    "event_date": _parse_iso(event_data.get("date")),
                    "price_id_external": ticket_data.get("priceId") or "",
                    "price_amount": price_data.get("amount") or 0,
                    "entered": ticket_data.get("entered", False),
                    "status": ticket_data.get("status") or "",
                    "payment_status": ticket_data.get("payment") or "",
                    "buyer_phone": phone,
                    "buyer_name": full_name,
                    "buyer_email": buyer_email,
                    "tamanho_camisete": tamanho_camisete,
                    "external_created_at": _parse_iso(ticket_data.get("createdAt")),
                    "external_updated_at": _parse_iso(ticket_data.get("updatedAt")),
                    "raw_payload": pay_data,
                },
            )

            # Invalidar cache de eventos (contagem de inscritos mudou)
            cache.delete(CACHE_EVENTS_KEY)

            messages.success(request, "Inscrição confirmada. Confirme o pagamento no seu telefone.")
            return redirect("events:registration_success", event_id=event_id)

    error_message = "Falha ao iniciar o pagamento. Verifique o número e tente novamente."
    if isinstance(pay_data, dict):
        api_message = pay_data.get("message") or pay_data.get("detail") or pay_data.get("error")
        if api_message:
            error_message = api_message

    messages.error(request, error_message)
    return render(request, "events/register.html", {"event": event, "tamanhos": tamanhos}, status=400)


def download_external_ticket_pdf(request, ticket_id: int):
    ticket = get_object_or_404(ExternalTicket, id=ticket_id)
    pdf_bytes = build_external_ticket_pdf(ticket)
    filename = f"ticket-{ticket.external_id}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def register_success(request, event_id):
    ticket = (
        ExternalTicket.objects
        .filter(event_id_external=event_id)
        .order_by("-created_at")
        .first()
    )
    if not ticket:
        raise Http404("Ticket não encontrado")

    return render(request, "events/registration_success.html", {
        "ticket": ticket,
        "event_name": ticket.event_name,
        "event_date": ticket.event_date,
        "event_location": ticket.event_location_details,
        "event_city": ticket.event_province,
        "buyer_name": ticket.buyer_name,
        "price_amount": ticket.price_amount,
    })