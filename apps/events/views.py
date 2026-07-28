import re
import logging
from datetime import datetime
from types import SimpleNamespace

import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.http import Http404, HttpResponse
from django.utils import timezone

from .models import ExternalTicket, TamanhoCamisete
from .pdf import build_external_ticket_pdf

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTES E CONFIGURAÇÕES
# =============================================================================

ETK_BASE = "https://eticketsmz.site"
ETK_TOKEN = "etk_live_3SZPEA7FNCZAdqjIaBIIbI7j"
TIMEOUT = 120

# =============================================================================
# OVERRIDES TEMPORÁRIOS PARA EVENTOS
# =============================================================================

EVENT_OVERRIDES = {
    "EVNT17827193458075": {  # ID do evento Run With Broto
        "name": "Last Winter Social",
        # UTC = 06:30 -> no fuso Africa/Maputo (UTC+2) vira 08:30
        "date": "2026-08-01T04:30:00Z",
        "description": (
            "No sábado, dia 1 de agosto de 2026, começa o dia com uma corrida de 5 km "
            "e prolonga a experiência num after run pensado para celebrar o movimento e a comunidade.\n\n"
            "Depois da corrida, junta-te ao Coffee Party, com DJs, ativações de marcas e um ambiente "
            "descontraído para conviver, recuperar energias e conhecer novas pessoas.\n\n"
            "Horário: 06:30 às 11:00\n\n"
            "Inscrição: 300 MZN\n\n"
            "As vagas são limitadas a apenas 100 participantes. Garante já o teu lugar."
        ),
        "imageUrl": "https://runwithbroto.com/static/img/lastwinter.jpeg",  # ← substitua pelo nome real da imagem
        # Se quiser alterar localização:
        # "location": {
        #     "province": "Maputo",
        #     "details": "Noctis",
        # }
    },
}


# =============================================================================
# FUNÇÕES AUXILIARES - API CLIENT
# =============================================================================

def _etk_request(method, path, json=None, timeout=TIMEOUT):
    """Faz requisição à API da ETickets e retorna o JSON decodificado."""
    url = f"{ETK_BASE}{path}"
    headers = {"Authorization": f"Bearer {ETK_TOKEN}"}
    if json is not None:
        headers["Content-Type"] = "application/json"
    try:
        resp = requests.request(method, url, headers=headers, json=json, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.error(f"Erro na requisição para {url}: {e}")
        raise


def _apply_event_overrides(event_data):
    """Aplica overrides temporários a um evento, se existirem."""
    event_id = str(event_data.get("id"))
    if event_id in EVENT_OVERRIDES:
        overrides = EVENT_OVERRIDES[event_id]
        for key, value in overrides.items():
            if isinstance(value, dict) and key in event_data and isinstance(event_data[key], dict):
                # Mescla dicionários aninhados (ex: location)
                event_data[key].update(value)
            else:
                event_data[key] = value
    return event_data


def _get_events_from_api():
    """Retorna a lista de eventos da API, com overrides aplicados."""
    data = _etk_request("GET", "/back/borrow/external/events")
    events = data.get("data", [])
    for e in events:
        _apply_event_overrides(e)
    return events


def _get_event_from_api(event_id):
    """Retorna os dados de um evento específico, com overrides aplicados."""
    data = _etk_request("GET", f"/back/borrow/external/events/{event_id}")
    event = data.get("data", {})
    _apply_event_overrides(event)
    return event


def _create_ticket_in_api(payload):
    """Cria um ticket na API e retorna a resposta."""
    return _etk_request("POST", "/back/borrow/external/tickets", json=payload)


def _parse_datetime(value):
    """Converte string ISO 8601 para datetime (suporta Z e offset)."""
    if not value:
        return None
    try:
        # Se terminar com Z, substitui por +00:00 para compatibilidade
        if value.endswith('Z'):
            value = value[:-1] + '+00:00'
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# =============================================================================
# UTILITÁRIOS DE MAPEAMENTO DE DADOS
# =============================================================================

def _build_event_context(event_data):
    """
    Transforma os dados brutos da API em um dicionário pronto para os templates.
    """
    start_at = _parse_datetime(event_data.get("date"))

    # Preço ativo (ou primeiro)
    prices = event_data.get("prices", [])
    active_price = next(
        (p for p in prices if (p.get("status") or "").lower() == "active"),
        prices[0] if prices else None,
    )
    amount = active_price.get("amount") if active_price else None
    ticket_price_display = f"{amount} MTn" if amount is not None else "—"

    category = event_data.get("category", "")
    event_type_display = category.replace("_", " ").title() if category else "—"

    image_url = event_data.get("imageUrl") or ""

    return {
        "id": event_data.get("id"),
        "slug": event_data.get("id"),
        "title": event_data.get("name"),
        "description": event_data.get("description") or "",
        "city": (event_data.get("location") or {}).get("province") or "",
        "meeting_point": (event_data.get("location") or {}).get("details") or "",
        "start_at": start_at,
        "image_url": image_url,
        "poster": SimpleNamespace(url=image_url) if image_url else None,
        "get_event_type_display": event_type_display,
        "ticket_price_display": ticket_price_display,
        "priceId": active_price.get("id") if active_price else None,
        "confirmed_count": event_data.get("totalTicketsPurchased") or 0,
    }


# =============================================================================
# VALIDAÇÃO DE FORMULÁRIO
# =============================================================================

def _validate_registration_data(post_data):
    """
    Valida os dados do formulário de inscrição.
    Retorna um dicionário com os dados limpos ou erros.
    """
    errors = {}
    cleaned = {}

    # Telefone
    phone = (post_data.get("phone") or "").strip()
    phone = re.sub(r"\D", "", phone)
    if not phone.startswith("258"):
        phone = f"258{phone}"
    if not re.fullmatch(r"258\d{9}", phone):
        errors["phone"] = "Número inválido. Use 84xxxxxxx, 85xxxxxxx, 86xxxxxxx, 87xxxxxxx ou já com 258."
    else:
        cleaned["phone"] = phone

    # Nome (opcional)
    cleaned["full_name"] = (post_data.get("full_name") or "").strip()

    # Email (opcional)
    email = (post_data.get("email") or "").strip()
    if email and "@" not in email:
        errors["email"] = "E-mail inválido."
    else:
        cleaned["email"] = email

    cleaned["tamanho_camisete"] = (post_data.get("tamanho_camisete") or "").strip()
    cleaned["payment"] = (post_data.get("payment") or "").strip()

    return cleaned, errors


# =============================================================================
# VIEWS
# =============================================================================

@require_http_methods(["GET"])
def event_list(request):
    """Lista todos os eventos futuros."""
    try:
        events_data = _get_events_from_api()
    except Exception as e:
        logger.error(f"Erro ao carregar eventos: {e}")
        events_data = []

    now = timezone.now()
    events = []
    for e in events_data:
        start_at = _parse_datetime(e.get("date"))
        if start_at and start_at < now:
            continue  # ignora eventos passados
        events.append({
            "event_id": e.get("id"),
            "title": e.get("name"),
            "slug": e.get("id"),
            "city": (e.get("location") or {}).get("province"),
            "meeting_point": (e.get("location") or {}).get("details"),
            "event_type": e.get("category"),
            "confirmed_count": e.get("totalTicketsPurchased", 0),
            "start_at": start_at,
            "image": e.get("imageUrl"),
        })

    events.sort(key=lambda x: x["start_at"] or datetime.max)
    return render(request, "events/agenda.html", {"events": events})


@require_http_methods(["GET"])
def event_detail(request, event_id):
    """Exibe detalhes de um evento específico."""
    try:
        event_data = _get_event_from_api(event_id)
    except requests.RequestException as e:
        logger.error(f"Erro ao buscar evento {event_id}: {e}")
        if getattr(e.response, 'status_code', None) == 404:
            raise Http404("Evento não encontrado")
        raise Http404("Erro ao carregar evento")

    if not event_data:
        raise Http404("Evento inválido")

    event = _build_event_context(event_data)
    return render(request, "events/event_detail.html", {"event": event})


@require_http_methods(["GET", "POST"])
def register_form(request, event_id):
    """Formulário de inscrição no evento (GET) e processamento (POST)."""
    # Busca evento
    try:
        event_data = _get_event_from_api(event_id)
    except Exception:
        messages.error(request, "Serviço indisponível. Tente novamente em instantes.")
        return redirect("events:event_detail", event_id=event_id)

    if not event_data:
        messages.error(request, "Evento inválido.")
        return redirect("events:event_list")

    event = _build_event_context(event_data)
    tamanhos = TamanhoCamisete.choices

    # GET: apenas exibe o formulário
    if request.method == "GET":
        return render(request, "events/register.html", {
            "event": event,
            "tamanhos": tamanhos,
        })

    # POST: valida e processa
    cleaned, errors = _validate_registration_data(request.POST)
    if errors:
        for field, msg in errors.items():
            messages.error(request, f"{field}: {msg}")
        return render(request, "events/register.html", {
            "event": event,
            "tamanhos": tamanhos,
        }, status=400)

    # Verifica se o evento tem priceId
    price_id = event.get("priceId")
    if not price_id:
        messages.error(request, "Este evento não tem preço ativo.")
        return render(request, "events/register.html", {
            "event": event,
            "tamanhos": tamanhos,
        }, status=400)

    # Monta payload para API
    payload = {
        "priceId": price_id,
        "eventId": event_id,
        "phone": cleaned["phone"],
    }
    if cleaned.get("email"):
        payload["email"] = cleaned["email"]
    if cleaned.get("full_name"):
        payload["fullName"] = cleaned["full_name"]
    if cleaned.get("payment"):
        payload["paymentMethod"] = cleaned["payment"]

    try:
        response_data = _create_ticket_in_api(payload)
    except Exception as e:
        logger.error(f"Erro ao criar ticket: {e}")
        messages.error(request, "Não foi possível processar o pagamento. Tente novamente.")
        return render(request, "events/register.html", {
            "event": event,
            "tamanhos": tamanhos,
        }, status=502)

    # Verifica resposta da API
    if response_data.get("status") == "success" and response_data.get("message") == "Ticket created successfully":
        ticket_data = response_data.get("data", {})
        _save_ticket_locally(ticket_data, cleaned, response_data, event_data)
        messages.success(
            request,
            "Inscrição confirmada com sucesso. Confirme o pagamento no seu telefone."
        )
        return redirect("events:registration_success", event_id=event_id)
    else:
        error_msg = response_data.get("message") or "Falha ao iniciar o pagamento."
        messages.error(request, error_msg)
        return render(request, "events/register.html", {
            "event": event,
            "tamanhos": tamanhos,
        }, status=400)


def _save_ticket_locally(ticket_data, cleaned_data, raw_payload, event_data):
    """Salva ou atualiza o ticket no banco local."""
    event = event_data
    location = event.get("location", {})
    price = ticket_data.get("price", {})

    defaults = {
        "event_id_external": ticket_data.get("eventId"),
        "event_name": event.get("name") or "",
        "event_category": event.get("category") or "",
        "event_province": location.get("province") or "",
        "event_location_details": location.get("details") or "",
        "event_image_url": event.get("imageUrl") or "",
        "event_date": _parse_datetime(event.get("date")),
        "price_id_external": ticket_data.get("priceId") or "",
        "price_amount": price.get("amount") or 0,
        "entered": ticket_data.get("entered", False),
        "status": ticket_data.get("status") or "",
        "payment_status": ticket_data.get("payment") or "",
        "buyer_phone": cleaned_data["phone"],
        "buyer_name": cleaned_data.get("full_name", ""),
        "buyer_email": cleaned_data.get("email", ""),
        "tamanho_camisete": cleaned_data.get("tamanho_camisete", ""),
        "external_created_at": _parse_datetime(ticket_data.get("createdAt")),
        "external_updated_at": _parse_datetime(ticket_data.get("updatedAt")),
        "raw_payload": raw_payload,
    }
    ExternalTicket.objects.update_or_create(
        external_id=ticket_data.get("id"),
        defaults=defaults,
    )


def register_success(request, event_id):
    """Página de sucesso após inscrição."""
    ticket = ExternalTicket.objects.filter(
        event_id_external=event_id
    ).order_by("-created_at").first()
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
    return render(request, "events/registration_success.html", context)


def download_external_ticket_pdf(request, ticket_id):
    """Baixa o PDF do ticket."""
    ticket = get_object_or_404(ExternalTicket, id=ticket_id)
    pdf_bytes = build_external_ticket_pdf(ticket)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="ticket-{ticket.external_id}.pdf"'
    return response
