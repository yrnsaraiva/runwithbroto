import hashlib
import hmac
import json
import re
import logging
import uuid
from types import SimpleNamespace

import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.views.decorators.cache import never_cache

from . import etk_client
from .models import ExternalTicket, TamanhoCamisete
from .pdf import build_external_ticket_pdf
from .sync import apply_api_ticket, ensure_local_ticket

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTES E CONFIGURAÇÕES
# =============================================================================

# =============================================================================
# EVENTOS COM ROTA TEMPORARIAMENTE DESATIVADA
# =============================================================================
# IDs de eventos cujas páginas (detalhe, inscrição, sucesso) devem devolver 404.
# Para reativar, basta remover o ID desta lista.

DISABLED_EVENT_IDS = set()

# Cliente da API partilhado (ver etk_client.py)
_get_events_from_api = etk_client.get_events
_get_event_from_api = etk_client.get_event
_create_ticket_in_api = etk_client.create_ticket
_parse_datetime = etk_client.parse_datetime


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
    is_free = amount is not None and float(amount) <= 0
    ticket_price_display = (
        "Grátis" if is_free else f"{amount} MTn" if amount is not None else "—"
    )

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
        "is_free": is_free,
        "is_preregistration": event_data.get("registrationMode") == "preregistration",
        "confirmation_deadline": _parse_datetime(event_data.get("confirmationDeadline")),
        "priceId": active_price.get("id") if active_price else None,
        "confirmed_count": event_data.get("totalTicketsPurchased") or 0,
    }


# =============================================================================
# VALIDAÇÃO DE FORMULÁRIO
# =============================================================================

# Métodos oferecidos no formulário (valores aceites pela API em paymentMethod).
PAYMENT_METHODS = [("mpesa", "M-Pesa"), ("emola", "e-Mola"), ("mkesh", "mKesh")]
DEFAULT_PAYMENT = "mpesa"


def _form_context(event, tamanhos, reference, selected=DEFAULT_PAYMENT):
    return {
        "event": event,
        "tamanhos": tamanhos,
        "external_reference": reference,
        "payment_methods": PAYMENT_METHODS,
        "selected_payment": selected,
    }


def _new_reference():
    return uuid.uuid4().hex


def _clean_reference(value):
    """Referência de idempotência vinda do formulário; gera outra se inválida."""
    value = (value or "").strip()
    return value if re.fullmatch(r"[0-9a-f]{32}", value) else _new_reference()


def _api_error_message(exc, default):
    """Mensagem legível de um erro HTTP da API (ex.: 402 pagamento recusado)."""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            return response.json().get("message") or default
        except ValueError:
            pass
    return default


def _normalize_phone(value):
    """Só dígitos, com o prefixo 258 (aceita 84xxxxxxx ou 25884xxxxxxx)."""
    phone = re.sub(r"\D", "", (value or "").strip())
    return phone if phone.startswith("258") else f"258{phone}"


def _validate_registration_data(post_data, is_free=False):
    """
    Valida os dados do formulário de inscrição.
    Retorna um dicionário com os dados limpos ou erros.

    Num bilhete gratuito não há pagamento: o método não é pedido nem enviado.
    """
    errors = {}
    cleaned = {}

    # Telefone
    phone = _normalize_phone(post_data.get("phone"))
    if not re.fullmatch(r"258\d{9}", phone):
        errors["phone"] = "Número inválido. Use 9 dígitos (ex.: 84xxxxxxx) ou já com 258."
    else:
        cleaned["phone"] = phone

    # Nome (opcional)
    cleaned["full_name"] = (post_data.get("full_name") or "").strip()

    # Email (opcional)
    email = (post_data.get("email") or "").strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        errors["email"] = "E-mail inválido."
    else:
        cleaned["email"] = email

    tamanho = (post_data.get("tamanho_camisete") or "").strip()
    if tamanho and tamanho not in TamanhoCamisete.values:
        errors["tamanho_camisete"] = "Tamanho de camisete inválido."
    else:
        cleaned["tamanho_camisete"] = tamanho
    if is_free:
        return cleaned, errors
    payment = (post_data.get("payment") or "").strip().lower()
    if payment not in dict(PAYMENT_METHODS):
        errors["payment"] = "Escolha o método de pagamento."
    else:
        cleaned["payment"] = payment

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

    events.sort(key=lambda x: (x["start_at"] is None, x["start_at"] or now))
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
    if event_id in DISABLED_EVENT_IDS:
        raise Http404("Inscrições encerradas.")

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
        return render(request, "events/register.html", _form_context(event, tamanhos, _new_reference()))

    # POST: valida e processa
    cleaned, errors = _validate_registration_data(request.POST, is_free=event["is_free"])
    reference = _clean_reference(request.POST.get("external_reference"))
    selected = request.POST.get("payment") or DEFAULT_PAYMENT
    if errors:
        for field, msg in errors.items():
            messages.error(request, f"{field}: {msg}")
        return render(request, "events/register.html", _form_context(event, tamanhos, reference, selected), status=400)

    # Verifica se o evento tem priceId
    price_id = event.get("priceId")
    if not price_id:
        messages.error(request, "Este evento não tem preço ativo.")
        return render(request, "events/register.html", _form_context(event, tamanhos, reference, selected), status=400)

    # Monta payload para API
    payload = {
        "priceId": price_id,
        "eventId": event_id,
        "phone": cleaned["phone"],
        # A API deduplica por externalReference: retry/duplo clique não cobra duas vezes.
        "externalReference": reference,
    }
    if cleaned.get("email"):
        payload["email"] = cleaned["email"]
    if cleaned.get("full_name"):
        payload["fullName"] = cleaned["full_name"]
    if cleaned.get("payment"):
        payload["paymentMethod"] = cleaned["payment"]

    try:
        response_data = _create_ticket_in_api(payload)
    except requests.HTTPError as e:
        logger.error(f"Erro ao criar ticket: {e}")
        code = getattr(e.response, "status_code", 502)
        messages.error(request, _api_error_message(e, "Não foi possível processar o pagamento. Tente novamente."))
        return render(request, "events/register.html", _form_context(event, tamanhos, reference, selected), status=code if code in (400, 402, 404, 409, 422) else 502)
    except Exception as e:
        logger.error(f"Erro ao criar ticket: {e}")
        messages.error(request, "Não foi possível processar o pagamento. Tente novamente.")
        return render(request, "events/register.html", _form_context(event, tamanhos, reference, selected), status=502)

    # Verifica resposta da API
    if response_data.get("status") == "success":
        ticket_data = response_data.get("data", {})
        ticket = _save_ticket_locally(ticket_data, cleaned, response_data, event_data)
        if event["is_preregistration"]:
            deadline = event["confirmation_deadline"]
            success_msg = "Pré-inscrição registada. Volte ao site para confirmar a sua presença" + (
                f" até {timezone.localtime(deadline):%d/%m/%Y %H:%M}." if deadline else "."
            )
        elif event["is_free"]:
            success_msg = "Inscrição confirmada."
        else:
            success_msg = "Inscrição registada. Confirme o pagamento no seu telefone."
        messages.success(request, success_msg)
        return redirect("events:registration_success", token=ticket.public_token)
    else:
        error_msg = response_data.get("message") or "Falha ao iniciar o pagamento."
        messages.error(request, error_msg)
        return render(request, "events/register.html", _form_context(event, tamanhos, reference, selected), status=400)


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
        "qr_value": ticket_data.get("qrValue") or "",
        "checkout_url": ticket_data.get("checkoutUrl") or "",
        "payment_instructions": ticket_data.get("paymentInstructions") or "",
        "status": ticket_data.get("status") or "",
        "payment_status": ticket_data.get("payment") or "",
        "confirmation_deadline": _parse_datetime(ticket_data.get("expiresAt"))
        if ticket_data.get("payment") == "preregistered" else None,
        "buyer_phone": cleaned_data["phone"],
        "buyer_name": cleaned_data.get("full_name", ""),
        "buyer_email": cleaned_data.get("email", ""),
        "tamanho_camisete": cleaned_data.get("tamanho_camisete", ""),
        "external_created_at": _parse_datetime(ticket_data.get("createdAt")),
        "external_updated_at": _parse_datetime(ticket_data.get("updatedAt")),
        "raw_payload": raw_payload,
    }
    ticket, _ = ExternalTicket.objects.update_or_create(
        external_id=ticket_data.get("id"),
        defaults=defaults,
    )
    return ticket


@never_cache
def register_success(request, token):
    """Página de sucesso após inscrição (acesso por token não adivinhável)."""
    ticket = get_object_or_404(ExternalTicket, public_token=token)

    context = {
        "ticket": ticket,
        "event_name": ticket.event_name,
        "event_date": ticket.event_date,
        "event_location": ticket.event_location_details,
        "event_city": ticket.event_province,
        "buyer_name": ticket.buyer_name,
        "price_amount": ticket.price_amount,
        "is_paid": ticket.payment_status.lower() in ("paid", "invited"),
        "is_preregistered": ticket.payment_status.lower() == "preregistered",
        "confirmation_deadline": ticket.confirmation_deadline,
        "deadline_passed": bool(
            ticket.confirmation_deadline and ticket.confirmation_deadline < timezone.now()
        ),
        "confirm_url": reverse("events:confirm_presence", args=[ticket.event_id_external]),
    }
    return render(request, "events/registration_success.html", context)


@never_cache
@require_http_methods(["GET"])
def ticket_status(request, token):
    """Estado do pagamento (JSON), usado pela página de sucesso para atualizar sozinha.

    Enquanto o bilhete não está pago, sonda a API; depois de pago responde só
    com o que está na base local.
    """
    ticket = get_object_or_404(ExternalTicket, public_token=token)
    if ticket.payment_status.lower() not in ("paid", "invited", "refunded", "preregistered"):
        try:
            ticket = apply_api_ticket(etk_client.get_ticket(ticket.external_id)) or ticket
        except Exception as e:
            logger.warning("Não foi possível sondar o bilhete %s: %s", ticket.external_id, e)
    return JsonResponse({
        "payment": ticket.payment_status,
        "paid": ticket.payment_status.lower() in ("paid", "invited"),
        "checkoutUrl": ticket.checkout_url,
    })


@csrf_exempt
@require_http_methods(["POST"])
def etk_webhook(request):
    """Aviso da API (ticket.paid, reembolsos...), assinado com HMAC-SHA256 em X-ETK-Signature."""
    secret = settings.ETICKETS_WEBHOOK_SECRET
    if not secret:
        return JsonResponse({"error": "webhook não configurado"}, status=503)
    expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("X-ETK-Signature", "")):
        return JsonResponse({"error": "assinatura inválida"}, status=401)
    try:
        payload = json.loads(request.body)
        data = payload["data"]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"error": "payload inválido"}, status=400)
    ticket = apply_api_ticket(data)
    return JsonResponse({"processed": bool(ticket)})


@never_cache
def download_external_ticket_pdf(request, token):
    """Baixa o PDF do ticket (acesso por token não adivinhável)."""
    ticket = get_object_or_404(ExternalTicket, public_token=token)
    if ticket.payment_status.lower() not in ("paid", "invited"):
        raise Http404("Bilhete ainda não confirmado.")
    pdf_bytes = build_external_ticket_pdf(ticket)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="ticket-{ticket.external_id}.pdf"'
    return response


# =============================================================================
# CONFIRMAÇÃO DE PRESENÇA (eventos em pré-inscrição)
# =============================================================================

def _mask_name(name):
    """'Ana Sousa Silva' -> 'Ana S. S.' — o telefone é a única credencial, por
    isso não se mostra o nome completo a quem só sabe o número."""
    parts = (name or "").split()
    if not parts:
        return "—"
    return " ".join([parts[0]] + [f"{p[0]}." for p in parts[1:]])


def _ticket_row(data):
    return {
        "id": data["id"],
        "name": _mask_name(data.get("fullName")),
        "payment": data.get("payment"),
        "created_at": _parse_datetime(data.get("createdAt")),
    }


@require_http_methods(["GET", "POST"])
def confirm_presence(request, event_id):
    """Confirmação de presença por telefone.

    Um mesmo telefone pode ter vários bilhetes (ex.: inscreveu amigos): lista
    todos, e o participante marca quais confirma.
    """
    if event_id in DISABLED_EVENT_IDS:
        raise Http404("Inscrições encerradas.")
    try:
        event_data = _get_event_from_api(event_id)
    except Exception:
        messages.error(request, "Serviço indisponível. Tente novamente em instantes.")
        return redirect("events:event_detail", event_id=event_id)
    if not event_data:
        raise Http404("Evento inválido")

    event = _build_event_context(event_data)
    deadline = event["confirmation_deadline"]
    closed = bool(deadline and deadline < timezone.now())
    ctx = {"event": event, "closed": closed}
    template = "events/confirm_presence.html"

    if not event["is_preregistration"]:
        messages.info(request, "Este evento não tem confirmação de presença.")
        return redirect("events:event_detail", event_id=event_id)
    if request.method == "GET":
        return render(request, template, ctx)

    phone = _normalize_phone(request.POST.get("phone"))
    ctx["phone"] = phone
    if not re.fullmatch(r"258\d{9}", phone):
        messages.error(request, "Número inválido. Use 9 dígitos (ex.: 84xxxxxxx).")
        return render(request, template, ctx, status=400)

    try:
        tickets = etk_client.list_tickets(event_id=event_id, phone=phone)
    except Exception as e:
        logger.error("Erro ao listar bilhetes de %s: %s", phone, e)
        messages.error(request, "Serviço indisponível. Tente novamente em instantes.")
        return render(request, template, ctx, status=502)
    by_id = {t["id"]: t for t in tickets}

    # Passo 2: confirmar os bilhetes marcados
    selected = request.POST.getlist("ticket_ids")
    if selected:
        results = []
        for ticket_id in selected:
            data = by_id.get(ticket_id)
            if not data or data.get("payment") != "preregistered":
                continue        # id que não é deste telefone/evento: ignora
            row = _ticket_row(data)
            try:
                confirmed = etk_client.confirm_ticket(ticket_id, phone)
                local = ensure_local_ticket(confirmed)
                row.update(ok=True, token=local.public_token)
            except requests.HTTPError as e:
                row.update(ok=False, error=_api_error_message(e, "Não foi possível confirmar."))
            except Exception as e:
                logger.error("Erro ao confirmar %s: %s", ticket_id, e)
                row.update(ok=False, error="Não foi possível confirmar. Tente novamente.")
            results.append(row)
        ctx["results"] = results
        return render(request, template, ctx)

    # Passo 1: mostrar os bilhetes deste telefone
    pending, done = [], []
    for data in tickets:
        row = _ticket_row(data)
        if data.get("payment") == "preregistered":
            pending.append(row)
        elif data.get("payment") in ("paid", "invited"):
            row["token"] = ensure_local_ticket(data).public_token
            done.append(row)
    ctx.update(pending=pending, done=done, searched=True)
    return render(request, template, ctx)
