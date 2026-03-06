from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_http_methods
import requests
from django.http import JsonResponse
from datetime import datetime
from django.http import Http404
from types import SimpleNamespace
import logging


#
logger = logging.getLogger(__name__)


@require_http_methods(["GET"])
def event_list(request):

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

            start_at = None
            if e.get("date"):
                try:
                    start_at = datetime.fromisoformat(
                        e["date"].replace("Z", "+00:00")
                    )
                except Exception:
                    pass

            events.append({
                "event_id": e.get("id"),
                "title": e.get("name"),
                "slug": e.get("id"),
                "city": e.get("location", {}).get("province"),
                "meeting_point": e.get("location", {}).get("details"),
                "event_type": e.get("category"),
                "confirmed_count": e.get("totalTicketsPurchased", 0),
                "start_at": start_at,
                "image": e.get("imageUrl")
            })

    except Exception as e:
        logger.error(f"Erro ao carregar eventos: {e}")

        # fallback seguro para o frontend
        events = []

    return render(request, "events/agenda.html", {
        "events": events
    })


@require_http_methods(["GET"])
def event_detail(request, event_id):
    url = f"https://eticketsmz.site/borrow/external/events/{event_id}"

    headers = {
        "Authorization": "Bearer etk_live_3SZPEA7FNCZAdqjIaBIIbI7j"
    }

    resp = requests.get(url, headers=headers, timeout=10)

    if resp.status_code == 404:
        raise Http404("Evento não encontrado")
    if not resp.ok:
        raise Http404(f"Erro ao carregar evento (status {resp.status_code})")

    payload = resp.json()

    # Pode vir como {"data": {...}, "status": "success"} ou direto {...}
    e = payload.get("data") if isinstance(payload, dict) else payload
    if not e:
        raise Http404("Evento inválido")

    # Converter data ISO -> datetime (para funcionar date:"l" / time:"H:i")
    start_at = None
    raw_date = e.get("date")
    if raw_date:
        try:
            start_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except ValueError:
            start_at = None

    # Preparar preço (ex: "500 MTn")
    prices = e.get("prices") or []
    first_price = prices[0] if prices else None
    amount = first_price.get("amount") if first_price else None
    ticket_price_display = f"{amount} MTn" if amount is not None else "—"

    # Mapear campos esperados pelo template
    event = {
        "id": e.get("id"),
        "title": e.get("name"),
        "description": e.get("description") or "",
        "city": (e.get("location") or {}).get("province") or "",
        "meeting_point": (e.get("location") or {}).get("details") or "",
        "start_at": start_at,
        "distance_min_km": None,
        "ticket_price_display": ticket_price_display,
        "image_url": e.get("imageUrl"),
        "category": e.get("category"),
        "confirmed_count": e.get("totalTicketsPurchased") or 0,
    }

    return render(request, "events/event_detail.html", {"event": event})


def _external_get_event(event_id: str) -> dict:
    url = "https://eticketsmz.site/borrow/external/events"

    headers = {
        "Authorization": "Bearer etk_live_3SZPEA7FNCZAdqjIaBIIbI7j"
    }

    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code == 404:
        raise Http404("Evento não encontrado")
    if not resp.ok:
        raise Http404(f"Erro ao carregar evento (status {resp.status_code})")

    payload = resp.json()
    e = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(e, dict) or not e:
        raise Http404("Evento inválido")

    return e


def _map_external_event_for_templates(e: dict) -> dict:
    # datetime para filtros do template
    start_at = None
    raw_date = e.get("date")
    if raw_date:
        try:
            start_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except ValueError:
            start_at = None

    # escolher price (preferir active)
    prices = e.get("prices") or []
    active = [p for p in prices if (p.get("status") or "").lower() == "active"]
    chosen = active[0] if active else (prices[0] if prices else None)

    amount = chosen.get("amount") if chosen else None
    ticket_price_display = f"{amount} MTn" if amount is not None else "—"

    # compatibilizar com {{ event.poster.url }}
    image_url = e.get("imageUrl") or ""
    poster = SimpleNamespace(url=image_url) if image_url else None

    # compatibilizar com {{ event.get_event_type_display }}
    category = e.get("category") or ""
    event_type_display = category.replace("_", " ").title() if category else "—"

    return {
        "id": e.get("id"),
        "event_id": e.get("id"),
        "slug": e.get("id"),
        "title": e.get("name"),
        "description": e.get("description") or "",
        "city": (e.get("location") or {}).get("province") or "",
        "meeting_point": (e.get("location") or {}).get("details") or "",
        "start_at": start_at,
        "distance_min_km": None,
        "ticket_price_display": ticket_price_display,
        "poster": poster,
        "image_url": image_url,
        "category": category,
        "get_event_type_display": event_type_display,  # <- chave para o template não quebrar
        "confirmed_count": e.get("totalTicketsPurchased") or 0,

        # úteis no POST
        "_price_id": chosen.get("id") if chosen else None,
    }

ETK_BASE = "https://eticketsmz.site"
ETK_TOKEN = "etk_live_3SZPEA7FNCZAdqjIaBIIbI7j"
TIMEOUT = 10


@require_http_methods(["GET", "POST"])
def register_form(request, event_id: str):
    url = f"{ETK_BASE}/borrow/external/events/{event_id}"
    headers = {"Authorization": f"Bearer {ETK_TOKEN}"}

    # 1) Buscar evento (para render e para obter priceId)
    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
    except requests.RequestException:
        messages.error(request, "Serviço indisponível. Tente novamente em instantes.")
        return redirect("events:event_detail", event_id=event_id)

    if resp.status_code == 404:
        raise Http404("Evento não encontrado")
    if not resp.ok:
        messages.error(request, "Não foi possível carregar o evento.")
        return redirect("events:event_list")

    payload = resp.json()
    e = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(e, dict) or not e:
        messages.error(request, "Evento inválido.")
        return redirect("events:event_list")

    # 2) Converter data
    start_at = None
    raw_date = e.get("date")
    if raw_date:
        try:
            start_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except ValueError:
            start_at = None

    # 3) Selecionar price ativo
    prices = e.get("prices") or []
    price_id = next((p.get("id") for p in prices if (p.get("status") or "").lower() == "active"), None)

    # 4) Compatibilidade com o template (poster.url + get_event_type_display)
    image_url = e.get("imageUrl") or ""
    poster = SimpleNamespace(url=image_url) if image_url else None

    category = e.get("category") or ""
    event_type_display = category.replace("_", " ").title() if category else "—"

    # (Opcional) preço para mostrar
    chosen = next((p for p in prices if (p.get("id") == price_id)), None) or (prices[0] if prices else None)
    amount = chosen.get("amount") if chosen else None
    ticket_price_display = f"{amount} MTn" if amount is not None else "—"

    event = {
        "id": e.get("id"),
        "slug": e.get("id"),  # usado no {% url 'events:register' event.slug %}
        "eventId": e.get("id"),
        "title": e.get("name"),
        "description": e.get("description") or "",
        "city": (e.get("location") or {}).get("province") or "",
        "meeting_point": (e.get("location") or {}).get("details") or "",
        "start_at": start_at,

        "poster": poster,  # ✅ para {{ event.poster.url }}
        "get_event_type_display": event_type_display,  # ✅ para {{ event.get_event_type_display }}
        "ticket_price_display": ticket_price_display,

        "priceId": price_id,
        "image_url": image_url,
        "confirmed_count": e.get("totalTicketsPurchased") or 0,
    }

    # GET: abre o formulário
    if request.method == "GET":
        return render(request, "events/register.html", {"event": event})

    # POST: enviar dados
    phone = (request.POST.get("phone") or "").strip()
    if not phone:
        messages.error(request, "Telefone é obrigatório.")
        return render(request, "events/register.html", {"event": event}, status=400)

    if not price_id:
        messages.error(request, "Este evento não tem preço ativo.")
        return render(request, "events/register.html", {"event": event}, status=400)

    body = {"priceId": price_id, "eventId": event_id, "phone": phone}
    api_headers = {"Content-Type": "application/json", "Authorization": f"Bearer {ETK_TOKEN}"}

    try:
        pay_resp = requests.request("GET", url, headers=api_headers, json=body, timeout=TIMEOUT)
    except requests.RequestException:
        messages.error(request, "Não foi possível processar o pagamento. Tente novamente.")
        return render(request, "events/register.html", {"event": event}, status=502)

    if pay_resp.ok:
        messages.success(request, "Pedido iniciado. Confirme o pagamento no seu telefone.")
        return redirect("events:registration_success", event_id=event_id)

    # erro da API (não expor o detalhe ao utilizador)
    messages.error(request, "Falha ao iniciar o pagamento. Verifique o número e tente novamente.")
    return render(request, "events/register.html", {"event": event}, status=400)


def register_success(request, event_id):
    return render(request, "events/registration_success.html", {"event_id": event_id})