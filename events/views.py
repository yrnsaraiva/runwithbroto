from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.views.decorators.http import require_http_methods
import requests
from django.http import JsonResponse
from datetime import datetime
from django.http import Http404
from types import SimpleNamespace


#
@require_http_methods(["GET"])
def event_list(request):
    url = "https://eticketsmz.site/borrow/external/events"

    headers = {
        "Authorization": "Bearer etk_live_3SZPEA7FNCZAdqjIaBIIbI7j"
    }

    response = requests.get(url, headers=headers)
    data = response.json()

    events = []

    for e in data.get("data", []):

        events.append({
            "event_id": e['id'],
            "title": e["name"],
            "slug": e["id"],
            "city": e["location"]["province"],
            "meeting_point": e["location"]["details"],
            "event_type": e["category"],
            "confirmed_count": e["totalTicketsPurchased"],
            "start_at": datetime.fromisoformat(e["date"].replace("Z", "+00:00")),
            "image": e["imageUrl"]
        })

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
    # --- 1) Buscar evento (precisas disso para renderizar o template)
    url = f"{ETK_BASE}/borrow/external/events/{event_id}"
    headers = {"Authorization": f"Bearer {ETK_TOKEN}"}

    resp = requests.get(url, headers=headers, timeout=TIMEOUT)
    if resp.status_code == 404:
        raise Http404("Evento não encontrado")
    if not resp.ok:
        raise Http404(f"Erro ao carregar evento (status {resp.status_code})")

    payload = resp.json()
    e = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(e, dict) or not e:
        raise Http404("Evento inválido")


    # --- 2) Mapear campos para o template register.html
    # data ISO -> datetime
    start_at = None
    raw_date = e.get("date")
    if raw_date:
        try:
            start_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except ValueError:
            start_at = None

    # escolher priceId
    # escolher price ativo
    prices = (e or {}).get("prices") or []
    price_id = next((p.get("id") for p in prices if (p.get("status") or "").lower() == "active"), None)

    # poster compatível com {{ event.poster.url }}
    image_url = e.get("imageUrl") or ""
    poster = SimpleNamespace(url=image_url) if image_url else None

    # compatível com {{ event.get_event_type_display }}
    category = e.get("category") or ""
    event_type_display = category.replace("_", " ").title() if category else "—"

    event = {
        "id": e.get("id"),
        "eventId": e.get("id"),
        "slug": e.get("id"),
        "title": e.get("name"),
        "description": e.get("description") or "",
        "city": (e.get("location") or {}).get("province") or "",
        "meeting_point": (e.get("location") or {}).get("details") or "",
        "start_at": start_at,
        "distance_min_km": None,
        "priceId": price_id,
        "image_url": e.get("imageUrl"),
        "category": e.get("category"),
        "confirmed_count": e.get("totalTicketsPurchased") or 0,
    }

    # --- 3) GET: abre o formulário
    if request.method == "GET":
        return render(request, "events/register.html", {"event": event})

    # --- 4) POST: formulário envia dados (chamar API externa)
    phone = (request.POST.get("phone") or "").strip()
    if not phone:
        return JsonResponse({"error": "Telefone é obrigatório."}, status=400)

    if not event["priceId"]:
        return JsonResponse({"error": "Evento sem preço ativo."}, status=400)

    prices = e.get("prices") or []
    first_price = prices[0] if prices else None


    body = {
        "priceId": event["priceId"],
        "eventId": event_id,
        "phone": phone,
    }

    api_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ETK_TOKEN}",
    }

    # reproduz teu curl: GET com body
    pay_resp = requests.request("GET", url, headers=api_headers, json=body, timeout=TIMEOUT)

    try:
        out = pay_resp.json()
    except ValueError:
        out = {"raw": pay_resp.text}

    # para TESTE: retornar resposta JSON
    return JsonResponse(
        {"ok": pay_resp.ok, "status_code": pay_resp.status_code, "sent": body, "response": out},
        status=200 if pay_resp.ok else 400,
    )