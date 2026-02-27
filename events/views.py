from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.views.decorators.http import require_http_methods

from .models import Event, City, EventType, EventRegistration, RegistrationStatus, PaymentStatus

from .pdfs import build_ticket_pdf


@require_http_methods(["GET"])
def event_list(request):
    """
    Lista eventos publicados.
    """
    city = request.GET.get("city", "").upper()
    etype = request.GET.get("type", "").upper()

    qs = Event.objects.filter(is_published=True, start_at__gte=timezone.now()).order_by("start_at")

    if city in dict(City.choices):
        qs = qs.filter(city=city)

    if etype in dict(EventType.choices):
        qs = qs.filter(event_type=etype)

    ctx = {
        "events": qs,
        "city_choices": City.choices,
        "type_choices": EventType.choices,
        "active_city": city,
        "active_type": etype,
    }
    return render(request, "events/agenda.html", ctx)


@require_http_methods(["GET"])
def event_detail(request, slug):
    event = get_object_or_404(Event, slug=slug, is_published=True)
    return render(request, "events/event_detail.html", {"event": event})


@require_http_methods(["GET"])
def register_form(request, slug: str):
    event = get_object_or_404(Event, slug=slug, is_published=True)
    return render(request, "events/register.html", {"event": event})


@require_http_methods(["POST"])
def register(request, slug: str):
    """
    Cria uma inscrição. Se o evento for grátis => confirma.
    Se for pago => redireciona para iniciar pagamento.
    """
    event = get_object_or_404(Event, slug=slug, is_published=True)

    if event.is_sold_out:
        messages.error(request, "Este evento está esgotado.")
        return redirect("events:event_detail", slug=event.slug)

    full_name = (request.POST.get("full_name") or "").strip()
    phone = (request.POST.get("phone") or "").strip()
    email = (request.POST.get("email") or "").strip()
    payment_method = request.POST.get("payment")

    if not full_name or not phone:
        messages.error(request, "Nome e telefone são obrigatórios.")
        return redirect("events:event_detail", slug=event.slug)

    # Evita duplicar inscrição do mesmo telefone no mesmo evento
    reg, created = EventRegistration.objects.get_or_create(
        event=event,
        phone=phone,
        status=RegistrationStatus.ACTIVE,
        defaults={
            "full_name": full_name,
            "email": email,
            "payment_status": PaymentStatus.UNPAID,
        }
    )
    if not created:
        # atualiza nome/email caso o utilizador mude
        reg.full_name = full_name
        reg.email = email
        reg.save(update_fields=["full_name", "email"])

    # Evento grátis => confirma
    if event.is_free:
        reg.payment_status = PaymentStatus.PAID
        reg.save(update_fields=["payment_status"])
        return redirect("events:registration_success", ticket_code=reg.ticket_code)

    # Pago => cria payment request e redirect via payments app
    return redirect(
        reverse("payments:start_event_payment") +
        f"?registration_id={reg.id}&method={payment_method}"
    )


@require_http_methods(["GET"])
def registration_success(request, ticket_code):
    reg = get_object_or_404(EventRegistration, ticket_code=ticket_code)

    return render(request, "events/registration_success.html", {"reg": reg})


def order_ticket_pdf(request, ticket_code):
    reg = get_object_or_404(EventRegistration, ticket_code=ticket_code)

    if reg.payment_status != PaymentStatus.PAID:
        return HttpResponse("Ticket indisponível: pagamento não confirmado.", status=403)

    pdf_bytes = build_ticket_pdf(reg)
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="ticket-{reg.ticket_code}.pdf"'
    return resp