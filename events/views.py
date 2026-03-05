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

#
# @require_http_methods(["GET"])
# def register_form(request, slug: str):
#     event = get_object_or_404(Event, slug=slug, is_published=True)
#     return render(request, "events/register.html", {"event": event})
#
#
# @require_http_methods(["POST"])
# def register(request, slug: str):
#     event = get_object_or_404(Event, slug=slug, is_published=True)
#
#     if event.is_sold_out:
#         messages.error(request, "Este evento está esgotado.")
#         return redirect("events:event_detail", slug=event.slug)
#
#     full_name = (request.POST.get("full_name") or "").strip()
#     phone = (request.POST.get("phone") or "").strip()
#     payment_method = (request.POST.get("payment") or "").strip()
#
#     if not full_name or not phone:
#         messages.error(request, "Nome e telefone são obrigatórios.")
#         return redirect("events:register_form", slug=event.slug)
#
#     # Evita duplicação acidental por clique duplo:
#     # se existir inscrição NÃO paga muito recente para o mesmo telefone/evento,
#     # reaproveita em vez de criar outra.
#     cooldown = timezone.now() - timedelta(seconds=45)
#
#     reg = (
#         EventRegistration.objects
#         .filter(event=event, phone=phone, created_at__gte=cooldown)
#         .exclude(payment_status=PaymentStatus.PAID)
#         .order_by("-created_at")
#         .first()
#     )
#
#     if not reg:
#         reg = EventRegistration.objects.create(
#             event=event,
#             phone=phone,
#             status=RegistrationStatus.ACTIVE,
#             full_name=full_name,
#             payment_status=PaymentStatus.UNPAID,
#         )
#     else:
#         # se reaproveitar, atualiza o nome (opcional)
#         reg.full_name = full_name
#         reg.save(update_fields=["full_name"])
#
#     # Evento grátis => confirma
#     if event.is_free:
#         reg.payment_status = PaymentStatus.PAID
#         reg.save(update_fields=["payment_status"])
#         return redirect("events:registration_success", ticket_code=reg.ticket_code)
#
#     # Pago => inicia pagamento
#     return redirect(
#         reverse("payments:start_event_payment") +
#         f"?registration_id={reg.id}&method={payment_method}"
#     )
#
#
# @require_http_methods(["GET"])
# def registration_success(request, ticket_code):
#     reg = get_object_or_404(EventRegistration, ticket_code=ticket_code)
#
#     return render(request, "events/registration_success.html", {"reg": reg})
#
#
# def order_ticket_pdf(request, ticket_code):
#     reg = get_object_or_404(EventRegistration, ticket_code=ticket_code)
#
#     if reg.payment_status != PaymentStatus.PAID:
#         return HttpResponse("Ticket indisponível: pagamento não confirmado.", status=403)
#
#     pdf_bytes = build_ticket_pdf(reg)
#     resp = HttpResponse(pdf_bytes, content_type="application/pdf")
#     resp["Content-Disposition"] = f'attachment; filename="ticket-{reg.ticket_code}.pdf"'
#     return resp