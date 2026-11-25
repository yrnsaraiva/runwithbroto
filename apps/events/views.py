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
from . import invites as invites_service
from .models import ExternalTicket, TamanhoCamisete, TemporaryRegistration, TemporaryRegistrationEntry
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
        # Nem todos os eventos têm camisetes: só nesses o formulário pede o tamanho.
        "offers_shirts": bool(event_data.get("offersShirts")),
        # A organização encerra as inscrições na API (checkbox do evento).
        "registration_open": event_data.get("registrationOpen", True) is not False,
        "is_preregistration": event_data.get("registrationMode") == "preregistration",
        "confirmation_deadline": _parse_datetime(event_data.get("confirmationDeadline")),
        "confirmation_opens_at": _parse_datetime(event_data.get("confirmationOpensAt")),
        # Só a organização abre a confirmação (na API); o site não decide.
        "confirmation_open": bool(event_data.get("confirmationOpen")),
        "priceId": active_price.get("id") if active_price else None,
        "confirmed_count": event_data.get("totalTicketsPurchased") or 0,
    }


# =============================================================================
# VALIDAÇÃO DE FORMULÁRIO
# =============================================================================

# Métodos oferecidos no formulário (valores aceites pela API em paymentMethod).
PAYMENT_METHODS = [("mpesa", "M-Pesa"), ("emola", "e-Mola"), ("mkesh", "mKesh")]
DEFAULT_PAYMENT = "mpesa"


def _form_context(event, tamanhos, reference, selected=DEFAULT_PAYMENT, size=""):
    return {
        "event": event,
        "tamanhos": tamanhos,
        "selected_size": size,
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


def _validate_registration_data(post_data, is_free=False, offers_shirts=False):
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

    # Tamanho: obrigatório nos eventos com camisetes; nos outros é ignorado
    # (nunca gravar um tamanho por omissão).
    cleaned["tamanho_camisete"] = ""
    if offers_shirts:
        tamanho = (post_data.get("tamanho_camisete") or "").strip()
        if tamanho not in TamanhoCamisete.values:
            errors["tamanho_camisete"] = "Escolha o tamanho da camisete."
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
    if not event["registration_open"]:
        messages.error(request, "As inscrições para este evento estão encerradas.")
        return redirect("events:event_detail", event_id=event_id)
    tamanhos = TamanhoCamisete.choices

    # GET: apenas exibe o formulário
    if request.method == "GET":
        return render(request, "events/register.html", _form_context(event, tamanhos, _new_reference()))

    # POST: valida e processa
    cleaned, errors = _validate_registration_data(
        request.POST, is_free=event["is_free"], offers_shirts=event["offers_shirts"])
    reference = _clean_reference(request.POST.get("external_reference"))
    selected = request.POST.get("payment") or DEFAULT_PAYMENT
    if errors:
        for field, msg in errors.items():
            messages.error(request, msg)
        return render(request, "events/register.html", _form_context(event, tamanhos, reference, selected, request.POST.get("tamanho_camisete", "")), status=400)

    # Verifica se o evento tem priceId
    price_id = event.get("priceId")
    if not price_id:
        messages.error(request, "Este evento não tem preço ativo.")
        return render(request, "events/register.html", _form_context(event, tamanhos, reference, selected, request.POST.get("tamanho_camisete", "")), status=400)

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
        return render(request, "events/register.html", _form_context(event, tamanhos, reference, selected, request.POST.get("tamanho_camisete", "")), status=code if code in (400, 402, 404, 409, 422) else 502)
    except Exception as e:
        logger.error(f"Erro ao criar ticket: {e}")
        messages.error(request, "Não foi possível processar o pagamento. Tente novamente.")
        return render(request, "events/register.html", _form_context(event, tamanhos, reference, selected, request.POST.get("tamanho_camisete", "")), status=502)

    # Verifica resposta da API
    if response_data.get("status") == "success":
        ticket_data = response_data.get("data", {})
        ticket = _save_ticket_locally(ticket_data, cleaned, response_data, event_data)
        if event["is_preregistration"]:
            deadline = event["confirmation_deadline"]
            success_msg = (
                "Pré-inscrição registada. A confirmação de presença será aberta "
                "mais perto do evento" + (
                    f" e terá de ser feita até {timezone.localtime(deadline):%d/%m/%Y %H:%M}."
                    if deadline else "."
                )
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
        return render(request, "events/register.html", _form_context(event, tamanhos, reference, selected, request.POST.get("tamanho_camisete", "")), status=400)


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
        "price_name": price.get("name") or "",
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

    # O link de confirmação só aparece quando a organização abriu a confirmação.
    confirmation_open = False
    if ticket.payment_status.lower() == "preregistered":
        try:
            confirmation_open = _build_event_context(
                _get_event_from_api(ticket.event_id_external)
            )["confirmation_open"]
        except Exception as e:
            logger.warning("Não foi possível ler o evento %s: %s", ticket.event_id_external, e)

    context = {
        "confirmation_open": confirmation_open,
        "ticket": ticket,
        "event_name": ticket.event_name,
        "event_date": ticket.event_date,
        "event_location": ticket.event_location_details,
        "event_city": ticket.event_province,
        "buyer_name": ticket.buyer_name,
        "price_amount": ticket.price_amount,
        "is_paid": ticket.payment_status.lower() in ("paid", "invited"),
        "is_preregistered": ticket.payment_status.lower() == "preregistered",
        "is_failed": ticket.payment_status.lower() == "failed",
        "confirmation_deadline": ticket.confirmation_deadline,
        "deadline_passed": bool(
            ticket.confirmation_deadline and ticket.confirmation_deadline < timezone.now()
        ),
        "confirm_url": reverse("events:confirm_presence", args=[ticket.event_id_external]),
        "ticket_type": ticket.ticket_type,
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
    not_open = not closed and not event["confirmation_open"]
    ctx = {"event": event, "closed": closed, "not_open": not_open}
    template = "events/confirm_presence.html"

    if not event["is_preregistration"]:
        messages.info(request, "Este evento não tem confirmação de presença.")
        return redirect("events:event_detail", event_id=event_id)
    if request.method == "GET" or closed or not_open:
        # Fechada (ainda não aberta, ou prazo terminado): nada é consultado
        # nem confirmado — a API recusa de qualquer forma.
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


# =============================================================================
# INSCRIÇÃO TEMPORÁRIA (camada temporária com vagas limitadas e stock de t-shirts)
# =============================================================================

def _validate_temp_registration_data(post_data, temp_reg):
    """
    Valida os dados do formulário de inscrição temporária.
    Retorna um dicionário com os dados limpos ou erros.
    """
    errors = {}
    cleaned = {}

    # Telefone
    phone = _normalize_phone(post_data.get("phone"))
    if not re.fullmatch(r"258\d{9}", phone):
        errors["phone"] = "Número inválido. Use 9 dígitos (ex.: 84xxxxxxx) ou já com 258."
    else:
        cleaned["phone"] = phone

    # Nome
    full_name = (post_data.get("full_name") or "").strip()
    if not full_name:
        errors["full_name"] = "Nome completo é obrigatório."
    else:
        cleaned["full_name"] = full_name

    # Email
    email = (post_data.get("email") or "").strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        errors["email"] = "E-mail inválido."
    else:
        cleaned["email"] = email

    # Tamanho de t-shirt: obrigatório se o evento exige
    cleaned["tamanho_camisete"] = ""
    if temp_reg.require_shirt_size:
        tamanho = (post_data.get("tamanho_camisete") or "").strip()
        if tamanho not in TamanhoCamisete.values:
            errors["tamanho_camisete"] = "Escolha o tamanho da camisete."
        elif not temp_reg.is_shirt_size_available(tamanho):
            errors["tamanho_camisete"] = f"Esgotado: não há mais t-shirts tamanho {tamanho}."
        else:
            cleaned["tamanho_camisete"] = tamanho

    # Pagamento: se não é gratuito, exige método de pagamento
    if temp_reg.require_payment:
        payment = (post_data.get("payment") or "").strip().lower()
        if payment not in dict(PAYMENT_METHODS):
            errors["payment"] = "Escolha o método de pagamento."
        else:
            cleaned["payment"] = payment

    return cleaned, errors


def _temp_registration_form_context(temp_reg, tamanhos, reference, selected_size="", selected_payment="mpesa", errors=None):
    """Contexto para o template do formulário de inscrição temporária."""
    event_data = None
    try:
        event_data = _get_event_from_api(temp_reg.event_id_external)
    except Exception as e:
        logger.warning("Não foi possível ler evento %s: %s", temp_reg.event_id_external, e)

    event = _build_event_context(event_data) if event_data else {
        "title": temp_reg.name,
        "description": temp_reg.description,
        "image_url": "",
        "start_at": None,
        "city": "",
        "meeting_point": "",
        "ticket_price_display": "—",
        "is_free": not temp_reg.require_payment,
        "offers_shirts": temp_reg.require_shirt_size,
    }

    # Preço do lote selecionado (ou ativo)
    price_amount = event.get("price_amount")
    price_display = "Grátis" if not temp_reg.require_payment else (f"{price_amount} MTn" if price_amount else "—")

    return {
        "temp_reg": temp_reg,
        "event": event,
        "tamanhos": tamanhos,
        "selected_size": selected_size,
        "external_reference": reference,
        "payment_methods": PAYMENT_METHODS,
        "selected_payment": selected_payment,
        "errors": errors or {},
        "price_display": price_display,
        "available_shirt_sizes": temp_reg.get_available_shirt_sizes(),
        "size_options": [
            {"value": value, "label": label, "available": temp_reg.get_shirt_stock_remaining(value)}
            for value, label in tamanhos
        ],
        "remaining_slots": temp_reg.remaining_slots,
    }


@require_http_methods(["GET", "POST"])
def temp_registration_form(request, slug):
    """Formulário de inscrição temporária (GET) e processamento (POST)."""
    temp_reg = get_object_or_404(TemporaryRegistration, slug=slug)

    if not temp_reg.is_open:
        messages.error(request, "Esta inscrição não está disponível no momento.")
        return render(request, "events/temp_registration_closed.html", {"temp_reg": temp_reg})

    tamanhos = TamanhoCamisete.choices

    if request.method == "GET":
        return render(request, "events/temp_register.html", _temp_registration_form_context(temp_reg, tamanhos, _new_reference()))

    # POST: valida e processa
    cleaned, errors = _validate_temp_registration_data(request.POST, temp_reg)
    reference = _clean_reference(request.POST.get("external_reference"))
    selected_size = request.POST.get("tamanho_camisete", "")
    selected_payment = request.POST.get("payment", "mpesa")

    if errors:
        return render(request, "events/temp_register.html",
                      _temp_registration_form_context(temp_reg, tamanhos, reference, selected_size, selected_payment, errors),
                      status=400)

    # Reserva atómica: bloqueia a inscrição, volta a verificar vagas e stock de t-shirts
    # (dois pedidos simultâneos não podem levar a última) e só então cria a entrada (pending).
    from django.db import transaction

    reservation_error = None
    with transaction.atomic():
        locked = TemporaryRegistration.objects.select_for_update().get(pk=temp_reg.pk)
        if not locked.is_open:
            reservation_error = {"slots": "As vagas esgotaram entretanto."}
        elif cleaned.get("tamanho_camisete") and not locked.is_shirt_size_available(cleaned["tamanho_camisete"]):
            reservation_error = {"tamanho_camisete": f"Esgotado: não há mais t-shirts tamanho {cleaned['tamanho_camisete']}."}
        else:
            entry = TemporaryRegistrationEntry.objects.create(
                registration=locked,
                full_name=cleaned["full_name"],
                phone=cleaned["phone"],
                email=cleaned["email"],
                tamanho_camisete=cleaned.get("tamanho_camisete", ""),
                external_reference=reference,
                payment_method=cleaned.get("payment", ""),
                status="pending",
            )

    if reservation_error:
        if "slots" in reservation_error:
            messages.error(request, reservation_error["slots"])
            return render(request, "events/temp_registration_closed.html", {"temp_reg": temp_reg}, status=409)
        return render(request, "events/temp_register.html",
                      _temp_registration_form_context(temp_reg, tamanhos, reference, selected_size, selected_payment, reservation_error),
                      status=400)

    # Busca preço/lote para criar ticket na API
    price_id = temp_reg.price_id_external
    if not price_id:
        # Usa o preço ativo do evento
        try:
            event_data = _get_event_from_api(temp_reg.event_id_external)
            prices = event_data.get("prices", [])
            active_price = next((p for p in prices if (p.get("status") or "").lower() == "active"), prices[0] if prices else None)
            if active_price:
                price_id = active_price.get("id")
        except Exception as e:
            logger.error("Erro ao buscar preço do evento %s: %s", temp_reg.event_id_external, e)

    if not price_id:
        entry.status = "failed"
        entry.payment_status = "error"
        entry.save(update_fields=["status", "payment_status"])
        messages.error(request, "Não foi possível determinar o preço. Contacte a organização.")
        return render(request, "events/temp_register.html",
                      _temp_registration_form_context(temp_reg, tamanhos, reference, selected_size, selected_payment, {"price": "Preço não configurado"}),
                      status=400)

    # Sem pagamento: emite um convite (bilhete gratuito normal) na API e guarda o
    # ExternalTicket local, para não ser preciso criar o bilhete à mão depois.
    if not temp_reg.require_payment:
        try:
            tickets = invites_service.create_invites(
                event_id=temp_reg.event_id_external,
                price_id=price_id,
                quantity=1,
                name=cleaned["full_name"],
                email=cleaned.get("email", ""),
                phone=cleaned["phone"],
                shirt_size=cleaned.get("tamanho_camisete", ""),
            )
        except requests.HTTPError as e:
            logger.error("Erro ao emitir convite da inscrição temporária: %s", e)
            code = getattr(e.response, "status_code", 502)
            entry.status = "failed"
            entry.payment_status = "failed"
            entry.save(update_fields=["status", "payment_status"])
            messages.error(request, _api_error_message(e, "Não foi possível emitir o bilhete. Tente novamente."))
            return render(request, "events/temp_register.html",
                          _temp_registration_form_context(temp_reg, tamanhos, reference, selected_size, selected_payment, {}),
                          status=code if code in (400, 402, 404, 409, 422) else 502)
        except Exception as e:
            logger.error("Erro ao emitir convite da inscrição temporária: %s", e)
            entry.status = "failed"
            entry.payment_status = "error"
            entry.save(update_fields=["status", "payment_status"])
            messages.error(request, "Não foi possível emitir o bilhete. Tente novamente.")
            return render(request, "events/temp_register.html",
                          _temp_registration_form_context(temp_reg, tamanhos, reference, selected_size, selected_payment, {}),
                          status=502)

        ticket = tickets[0]
        entry.external_ticket_id = ticket.external_id
        entry.ticket_public_token = ticket.public_token
        entry.payment_status = ticket.payment_status or "invited"
        entry.save(update_fields=["external_ticket_id", "ticket_public_token", "payment_status"])
        return _confirm_temp_registration(entry, request)

    # Monta payload para API
    payload = {
        "priceId": price_id,
        "eventId": temp_reg.event_id_external,
        "phone": cleaned["phone"],
        "externalReference": reference,
    }
    if cleaned.get("email"):
        payload["email"] = cleaned["email"]
    if cleaned.get("full_name"):
        payload["fullName"] = cleaned["full_name"]
    if cleaned.get("payment"):
        payload["paymentMethod"] = cleaned["payment"]
    if cleaned.get("tamanho_camisete"):
        payload["shirtSize"] = cleaned["tamanho_camisete"]

    try:
        response_data = _create_ticket_in_api(payload)
    except requests.HTTPError as e:
        logger.error(f"Erro ao criar ticket temporário: {e}")
        code = getattr(e.response, "status_code", 502)
        entry.status = "failed"
        entry.payment_status = "failed"
        entry.save(update_fields=["status", "payment_status"])
        messages.error(request, _api_error_message(e, "Não foi possível processar o pagamento. Tente novamente."))
        return render(request, "events/temp_register.html",
                      _temp_registration_form_context(temp_reg, tamanhos, reference, selected_size, selected_payment, {}),
                      status=code if code in (400, 402, 404, 409, 422) else 502)
    except Exception as e:
        logger.error(f"Erro ao criar ticket temporário: {e}")
        entry.status = "failed"
        entry.payment_status = "error"
        entry.save(update_fields=["status", "payment_status"])
        messages.error(request, "Não foi possível processar o pagamento. Tente novamente.")
        return render(request, "events/temp_register.html",
                      _temp_registration_form_context(temp_reg, tamanhos, reference, selected_size, selected_payment, {}),
                      status=502)

    # Verifica resposta da API
    if response_data.get("status") == "success":
        ticket_data = response_data.get("data", {})
        entry.external_ticket_id = ticket_data.get("id", "")
        entry.payment_status = ticket_data.get("payment", "pending")
        entry.save(update_fields=["external_ticket_id", "payment_status"])

        # Se pagamento já confirmado (pago ou convite), confirma a inscrição
        if entry.payment_status.lower() in ("paid", "invited"):
            return _confirm_temp_registration(entry, request)

        # Pagamento pendente - redireciona para página de aguardo
        messages.success(request, "Inscrição registada. Confirme o pagamento no seu telefone.")
        return redirect("events:temp_registration_waiting", token=entry.ticket_public_token or reference)
    else:
        error_msg = response_data.get("message") or "Falha ao iniciar o pagamento."
        entry.status = "failed"
        entry.payment_status = "failed"
        entry.save(update_fields=["status", "payment_status"])
        messages.error(request, error_msg)
        return render(request, "events/temp_register.html",
                      _temp_registration_form_context(temp_reg, tamanhos, reference, selected_size, selected_payment, {}),
                      status=400)


def _confirm_temp_registration(entry, request):
    """Confirma uma inscrição temporária: incrementa vagas usadas e guarda token do ticket."""
    from django.db import transaction

    with transaction.atomic():
        entry.refresh_from_db()
        if entry.status == "confirmed":
            if not entry.ticket_public_token:
                entry.ticket_public_token = uuid.uuid4()
                entry.save(update_fields=["ticket_public_token", "updated_at"])
            return redirect("events:temp_registration_success", token=entry.ticket_public_token)

        temp_reg = entry.registration
        temp_reg.increment_used_slots()
        entry.status = "confirmed"
        entry.confirmed_at = timezone.now()

        # Busca o ticket na API para obter o public_token
        if entry.external_ticket_id and not entry.ticket_public_token:
            try:
                ticket_data = etk_client.get_ticket(entry.external_ticket_id)
                local_ticket = ensure_local_ticket(ticket_data)
                entry.ticket_public_token = local_ticket.public_token
            except Exception as e:
                logger.warning("Não foi possível obter token do ticket %s: %s", entry.external_ticket_id, e)

        # O tamanho da camisete só existe no site (a API não o guarda): copia-o para o bilhete local
        if entry.ticket_public_token and entry.tamanho_camisete:
            ExternalTicket.objects.filter(public_token=entry.ticket_public_token).update(
                tamanho_camisete=entry.tamanho_camisete)

        # Inscrições gratuitas (ou falha na API) não têm ticket externo: gera token local
        if not entry.ticket_public_token:
            entry.ticket_public_token = uuid.uuid4()

        entry.save(update_fields=["status", "confirmed_at", "ticket_public_token", "updated_at"])

    _send_temp_ticket_email(entry, request)

    # Sem request (sondagem JSON / webhook) não há mensagens flash a mostrar
    if request is not None:
        messages.success(request, entry.registration.custom_success_message or "Inscrição confirmada com sucesso!")
    return redirect("events:temp_registration_success", token=entry.ticket_public_token)


def _send_temp_ticket_email(entry, request):
    """Envia o bilhete por e-mail na primeira confirmação. Nunca desfaz a inscrição se falhar."""
    if not entry.email or not entry.ticket_public_token or not invites_service.email_enabled():
        return
    ticket = ExternalTicket.objects.filter(public_token=entry.ticket_public_token).first()
    if not ticket or ticket.invite_sent_at:
        return
    try:
        link = invites_service.invite_link(request, ticket)
        invites_service.send_ticket_email(ticket, link, to=entry.email, name=entry.full_name)
    except Exception:
        logger.exception("Não foi possível enviar o bilhete %s por e-mail", ticket.external_id)


@never_cache
@require_http_methods(["GET"])
def temp_registration_waiting(request, token):
    """Página de aguardo enquanto pagamento é processado."""
    entry = get_object_or_404(TemporaryRegistrationEntry, external_reference=token)
    temp_reg = entry.registration

    context = {
        "entry": entry,
        "temp_reg": temp_reg,
        "event_name": temp_reg.name,
        "checkout_url": entry.checkout_url if hasattr(entry, 'checkout_url') else "",
    }
    return render(request, "events/temp_registration_waiting.html", context)


@never_cache
@require_http_methods(["GET"])
def temp_registration_status(request, token):
    """Estado do pagamento (JSON) para a página de aguardo."""
    entry = get_object_or_404(TemporaryRegistrationEntry, external_reference=token)

    # Se ainda pendente, sonda a API
    if entry.status == "pending" and entry.external_ticket_id:
        try:
            ticket_data = etk_client.get_ticket(entry.external_ticket_id)
            payment_status = ticket_data.get("payment", "").lower()
            entry.payment_status = ticket_data.get("payment", "")
            entry.save(update_fields=["payment_status", "updated_at"])

            if payment_status in ("paid", "invited"):
                # Confirma automaticamente e responde em JSON (a página de aguardo faz o redirect)
                _confirm_temp_registration(entry, None)
                entry.refresh_from_db()
        except Exception as e:
            logger.warning("Não foi possível sondar ticket %s: %s", entry.external_ticket_id, e)

    return JsonResponse({
        "status": entry.status,
        "payment_status": entry.payment_status,
        "confirmed": entry.status == "confirmed",
        "token": str(entry.ticket_public_token) if entry.ticket_public_token else None,
        "redirect_url": reverse("events:temp_registration_success", args=[entry.ticket_public_token]) if entry.ticket_public_token else None,
    })


@never_cache
@require_http_methods(["GET"])
def temp_registration_success(request, token):
    """Página de sucesso após confirmação da inscrição temporária."""
    entry = get_object_or_404(TemporaryRegistrationEntry, ticket_public_token=token)

    if entry.status != "confirmed":
        messages.error(request, "Esta inscrição ainda não foi confirmada.")
        return redirect("events:temp_registration_waiting", token=entry.external_reference)

    context = {
        "entry": entry,
        "temp_reg": entry.registration,
        "event_name": entry.registration.name,
        "buyer_name": entry.full_name,
        "tamanho_camisete": entry.tamanho_camisete,
    }
    return render(request, "events/temp_registration_success.html", context)


@csrf_exempt
@require_http_methods(["POST"])
def temp_registration_webhook(request):
    """Webhook para atualização de status de pagamento de inscrições temporárias."""
    secret = settings.ETICKETS_WEBHOOK_SECRET
    if not secret:
        return JsonResponse({"error": "webhook não configurado"}, status=503)

    import hmac
    import hashlib
    expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("X-ETK-Signature", "")):
        return JsonResponse({"error": "assinatura inválida"}, status=401)

    import json
    try:
        payload = json.loads(request.body)
        data = payload["data"]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"error": "payload inválido"}, status=400)

    ticket_id = data.get("id")
    payment_status = (data.get("payment") or "").lower()

    if not ticket_id:
        return JsonResponse({"error": "ticket_id ausente"}, status=400)

    try:
        entry = TemporaryRegistrationEntry.objects.get(external_ticket_id=ticket_id)
    except TemporaryRegistrationEntry.DoesNotExist:
        return JsonResponse({"processed": False, "reason": "entry not found"})

    entry.payment_status = data.get("payment", "")

    if payment_status in ("paid", "invited") and entry.status == "pending":
        _confirm_temp_registration(entry, None)
    elif payment_status == "failed":
        entry.status = "failed"
        entry.save(update_fields=["status", "payment_status", "updated_at"])

    return JsonResponse({"processed": True})
