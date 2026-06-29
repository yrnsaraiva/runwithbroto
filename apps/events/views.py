from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_http_methods
import requests
from django.http import JsonResponse
from datetime import datetime
from django.http import Http404, HttpResponse
from types import SimpleNamespace
import logging
import re
from .models import ExternalTicket, TamanhoCamisete
from django.shortcuts import get_object_or_404
from .pdf import build_external_ticket_pdf


#
logger = logging.getLogger(__name__)

#EVNT17827193458075
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
    url = "https://eticketsmz.site/back/borrow/external/events"

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
TIMEOUT = 120


@require_http_methods(["GET", "POST"])
def register_form(request, event_id: str):
    event_url = f"{ETK_BASE}/back/borrow/external/events/{event_id}"
    ticket_url = f"{ETK_BASE}/back/borrow/external/tickets"
    auth_headers = {"Authorization": f"Bearer {ETK_TOKEN}"}

    # 1) Buscar evento para renderizar o formulário e obter priceId
    try:
        resp = requests.get(event_url, headers=auth_headers, timeout=TIMEOUT)
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

    # caso a API devolva lista em data
    if isinstance(e, list):
        e = e[0] if e else None

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

    # 3) Selecionar preço ativo
    prices = e.get("prices") or []
    price_id = next(
        (p.get("id") for p in prices if (p.get("status") or "").lower() == "active"),
        None
    )
    chosen_price = next(
        (p for p in prices if p.get("id") == price_id),
        None
    ) or (prices[0] if prices else None)

    amount = chosen_price.get("amount") if chosen_price else None
    ticket_price_display = f"{amount} MTn" if amount is not None else "—"

    category = e.get("category") or ""
    event_type_display = category.replace("_", " ").title() if category else "—"
    tamanhos = TamanhoCamisete.choices

    event = {
        "id": e.get("id"),
        "slug": e.get("id"),
        "eventId": e.get("id"),
        "title": e.get("name"),
        "description": e.get("description") or "",
        "city": (e.get("location") or {}).get("province") or "",
        "meeting_point": (e.get("location") or {}).get("details") or "",
        "start_at": start_at,
        "poster_url": e.get("imageUrl") or "",
        "get_event_type_display": event_type_display,
        "ticket_price_display": ticket_price_display,
        "priceId": price_id,
        "image_url": e.get("imageUrl") or "",
        "confirmed_count": e.get("totalTicketsPurchased") or 0,
    }

    # GET: só renderiza o formulário
    if request.method == "GET":
        return render(request, "events/register.html", {"event": event, "tamanhos": tamanhos})

    # POST: validar e enviar compra
    phone = (request.POST.get("phone") or "").strip()
    full_name = (request.POST.get("full_name") or "").strip()
    buyer_email = (request.POST.get("email") or "").strip()
    tamanho_camisete = (request.POST.get("tamanho_camisete") or "").strip()
    payment = (request.POST.get("payment") or "").strip()

    # normalizar telefone: remover tudo que não for dígito
    phone = re.sub(r"\D", "", phone)

    # garantir prefixo 258
    if not phone.startswith("258"):
        phone = f"258{phone}"

    # validar formato final: 258 + 9 dígitos
    if not re.fullmatch(r"258\d{9}", phone):
        messages.error(
            request,
            "Número inválido. Use 84xxxxxxx, 85xxxxxxx, 86xxxxxxx, 87xxxxxxx ou já com 258."
        )
        return render(request, "events/register.html", {"event": event}, status=400)

    if not price_id:
        messages.error(request, "Este evento não tem preço ativo.")
        return render(request, "events/register.html", {"event": event}, status=400)

    body = {
        "priceId": price_id,
        "eventId": event_id,
        "phone": phone,
        "email": buyer_email,
    }

    # incluir só se a API externa suportar estes campos
    if full_name:
        body["fullName"] = full_name
    if payment:
        body["paymentMethod"] = payment
    if buyer_email:
        body["email"] = buyer_email

    api_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ETK_TOKEN}",
    }

    try:
        pay_resp = requests.post(ticket_url, headers=api_headers, json=body, timeout=TIMEOUT)
    except requests.RequestException:
        messages.error(request, "Não foi possível processar o pagamento. Tente novamente.")
        return render(request, "events/register.html", {"event": event}, status=502)

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

            created_at = None
            updated_at = None
            event_date = None

            raw_created_at = ticket_data.get("createdAt")
            raw_updated_at = ticket_data.get("updatedAt")
            raw_event_date = event_data.get("date")

            if raw_created_at:
                try:
                    created_at = datetime.fromisoformat(raw_created_at.replace("Z", "+00:00"))
                except ValueError:
                    created_at = None

            if raw_updated_at:
                try:
                    updated_at = datetime.fromisoformat(raw_updated_at.replace("Z", "+00:00"))
                except ValueError:
                    updated_at = None

            if raw_event_date:
                try:
                    event_date = datetime.fromisoformat(raw_event_date.replace("Z", "+00:00"))
                except ValueError:
                    event_date = None

            ExternalTicket.objects.update_or_create(
                external_id=ticket_data.get("id"),
                defaults={
                    "event_id_external": ticket_data.get("eventId"),
                    "event_name": event_data.get("name") or "",
                    "event_category": event_data.get("category") or "",

                    "event_province": location_data.get("province") or "",
                    "event_location_details": location_data.get("details") or "",
                    "event_image_url": event_data.get("imageUrl") or "",
                    "event_date": event_date,

                    "price_id_external": ticket_data.get("priceId") or "",
                    "price_amount": price_data.get("amount") or 0,

                    "entered": ticket_data.get("entered", False),
                    "status": ticket_data.get("status") or "",
                    "payment_status": ticket_data.get("payment") or "",

                    "buyer_phone": phone,
                    "buyer_name": full_name,
                    "buyer_email": buyer_email,
                    "tamanho_camisete": tamanho_camisete,

                    "external_created_at": created_at,
                    "external_updated_at": updated_at,

                    "raw_payload": pay_data,
                },
            )

            messages.success(
                request,
                "Inscrição confirmada com sucesso. Confirme o pagamento no seu telefone."
            )
            return redirect("events:registration_success", event_id=event_id)

    # tentar mostrar mensagem da API, sem expor detalhes demais
    error_message = "Falha ao iniciar o pagamento. Verifique o número e tente novamente."
    if isinstance(pay_data, dict):
        api_message = (
            pay_data.get("message")
            or pay_data.get("detail")
            or pay_data.get("error")
        )
        if api_message:
            error_message = api_message

    messages.error(request, error_message)
    return render(request, "events/register.html", {"event": event}, status=400)


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

    context = {
        "ticket": ticket,
        "event_name": ticket.event_name,
        "event_date": ticket.event_date,
        "event_location": ticket.event_location_details,
        "event_city": ticket.event_province,
        "buyer_name": ticket.buyer_name,
        "price_amount": ticket.price_amount,
    }

    return render(
        request,
        "events/registration_success.html",
        context
    )
