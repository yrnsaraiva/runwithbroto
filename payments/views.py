from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from events.models import EventRegistration, PaymentStatus  # usa teu enum do events
from .models import Payment, PaymentStatus
from .services.paysuite import create_payment_request, PaySuiteError


@require_http_methods(["GET"])
def start_event_payment(request):
    registration_id = request.GET.get("registration_id")
    method = request.GET.get("method")

    reg = get_object_or_404(EventRegistration, id=registration_id)

    if reg.payment_status == PaymentStatus.PAID:
        return redirect("events:registration_success", ticket_code=reg.ticket_code)

    amount = reg.event.price
    reference = f"REG{reg.id}"

    payment, _ = Payment.objects.get_or_create(
        registration=reg,
        defaults={
            "reference": reference,
            "amount": amount,
        }
    )

    return_url = request.build_absolute_uri(reverse("payments:return"))
    callback_url = request.build_absolute_uri(reverse("payments:webhook_paysuite"))

    resp = create_payment_request(
        amount=str(payment.amount),
        reference=payment.reference,
        description=f"Run With Broto • {reg.event.title}",
        return_url=return_url,
        callback_url=callback_url,
        method=method,
    )

    payment.paysuite_id = resp["id"]
    payment.checkout_url = resp["checkout_url"]
    payment.save(update_fields=["paysuite_id", "checkout_url", "updated_at"])

    return redirect(payment.checkout_url)


@require_http_methods(["GET"])
def payment_return(request):
    """
    Página de retorno (UX). Confirmação real vem do webhook.
    """
    return render(request, "payments/return.html")