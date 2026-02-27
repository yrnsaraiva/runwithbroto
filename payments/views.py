import logging
from decimal import Decimal

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

from events.models import EventRegistration, PaymentStatus as RegPaymentStatus
from .models import Payment, PaymentStatus as PayPaymentStatus, PaymentMethod
from .services.paysuite import create_payment_request, get_payment, PaySuiteError

logger = logging.getLogger(__name__)


def _make_reference(reg: EventRegistration) -> str:
    base = (reg.ticket_code or f"RWB{reg.id}").replace("-", "").strip()
    base = "".join(ch for ch in base if ch.isalnum())
    return base[:32] or f"RWB{reg.id}"


def _interpret_remote_payment(remote: dict) -> str:
    """
    Normaliza status remoto -> "paid" | "failed" | "pending"
    PaySuite no teu payload usa: transaction.status == "completed"
    """
    tx = remote.get("transaction") or {}
    tx_status = (tx.get("status") or "").lower()

    if tx_status == "completed":
        return "paid"
    if tx_status in ("failed", "cancelled", "canceled"):
        return "failed"
    return "pending"


@require_http_methods(["GET"])
def start_event_payment(request):
    registration_id = request.GET.get("registration_id")
    method = (request.GET.get("method") or "").strip().lower()

    reg = get_object_or_404(EventRegistration, id=registration_id)

    if reg.payment_status == RegPaymentStatus.PAID:
        return redirect("events:registration_success", ticket_code=reg.ticket_code)

    if method and method not in dict(PaymentMethod.choices):
        messages.error(request, "Método de pagamento inválido.")
        return redirect("events:register_form", slug=reg.event.slug)

    amount = reg.amount_due or Decimal("0.00")
    if amount <= 0:
        reg.payment_status = RegPaymentStatus.PAID
        reg.save(update_fields=["payment_status"])
        return redirect("events:registration_success", ticket_code=reg.ticket_code)

    payment, _ = Payment.objects.get_or_create(
        registration=reg,
        defaults={
            "reference": _make_reference(reg),
            "amount": amount,
            "currency": "MZN",
            "status": PayPaymentStatus.PENDING,
            "method": method or None,
        }
    )

    if payment.status == PayPaymentStatus.PAID:
        reg.payment_status = RegPaymentStatus.PAID
        reg.save(update_fields=["payment_status"])
        return redirect("events:registration_success", ticket_code=reg.ticket_code)

    return_url = request.build_absolute_uri(reverse("payments:return")) + f"?ref={payment.reference}"
    callback_url = request.build_absolute_uri(reverse("payments:webhook_paysuite"))
    description = f"RunWithBroto • {reg.event.title} • {reg.ticket_code}"

    try:
        resp = create_payment_request(
            amount=str(amount),
            reference=payment.reference,
            description=description,
            return_url=return_url,
            callback_url=callback_url,
            method=payment.method,
        )
    except PaySuiteError as e:
        logger.exception("PaySuite create_payment_request failed")
        messages.error(request, f"Falha ao iniciar pagamento: {e}")
        return redirect("events:register_form", slug=reg.event.slug)

    payment.paysuite_id = resp.get("id")
    payment.checkout_url = resp.get("checkout_url")
    payment.raw_provider_payload = resp
    payment.status = PayPaymentStatus.PENDING
    payment.save(update_fields=["paysuite_id", "checkout_url", "raw_provider_payload", "status", "updated_at"])

    if not payment.checkout_url:
        messages.error(request, "PaySuite não retornou checkout_url.")
        return redirect("events:register_form", slug=reg.event.slug)

    return redirect(payment.checkout_url)


@require_http_methods(["GET"])
def payment_return(request):
    ref = (request.GET.get("ref") or "").strip()
    if not ref:
        return render(request, "payments/return.html", {"state": "verifying"})

    payment = get_object_or_404(Payment, reference=ref)
    reg = payment.registration

    # já confirmado
    if payment.status == PayPaymentStatus.PAID or reg.payment_status == RegPaymentStatus.PAID:
        return redirect("events:registration_success", ticket_code=reg.ticket_code)

    if not payment.paysuite_id:
        return render(request, "payments/return.html", {"payment": payment, "state": "verifying"})

    try:
        remote = get_payment(payment.paysuite_id)
    except PaySuiteError:
        return render(request, "payments/return.html", {"payment": payment, "state": "verifying"})

    # guarda sempre
    payment.raw_provider_payload = remote

    normalized = _interpret_remote_payment(remote)

    tx = remote.get("transaction") or {}

    if normalized == "paid":
        payment.status = PayPaymentStatus.PAID
        payment.transaction_id = str(tx.get("id") or tx.get("transaction_id") or payment.transaction_id)

        paid_at = tx.get("paid_at") or remote.get("paid_at")
        payment.paid_at = parse_datetime(paid_at) if paid_at else timezone.now()

        payment.save(update_fields=["status", "transaction_id", "paid_at", "raw_provider_payload", "updated_at"])

        reg.payment_status = RegPaymentStatus.PAID
        reg.save(update_fields=["payment_status"])

        return redirect("events:registration_success", ticket_code=reg.ticket_code)

    if normalized == "failed":
        payment.status = PayPaymentStatus.FAILED
        payment.save(update_fields=["status", "raw_provider_payload", "updated_at"])

        reg.payment_status = RegPaymentStatus.FAILED
        reg.save(update_fields=["payment_status"])

        return render(request, "payments/return.html", {"payment": payment, "state": "failed"})

    payment.status = PayPaymentStatus.PENDING
    payment.save(update_fields=["status", "raw_provider_payload", "updated_at"])
    return render(request, "payments/return.html", {"payment": payment, "state": "verifying"})


@require_http_methods(["GET"])
def payment_status(request):
    ref = (request.GET.get("ref") or "").strip()
    if not ref:
        return JsonResponse({"ok": False}, status=400)

    payment = Payment.objects.select_related("registration").filter(reference=ref).first()
    if not payment:
        return JsonResponse({"ok": False}, status=404)

    reg = payment.registration
    return JsonResponse({
        "ok": True,
        "payment_status": payment.status,
        "registration_payment_status": reg.payment_status,
        "ticket_code": reg.ticket_code,
    })