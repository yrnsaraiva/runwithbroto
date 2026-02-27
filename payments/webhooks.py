import json
import hmac
import hashlib

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, HttpResponseForbidden
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Payment, PaymentStatus as PaymentState  # <-- usa o enum do payments (ajusta ao teu model)
from events.models import PaymentStatus as RegPaymentStatus  # <-- enum da inscrição


def _verify_signature(raw: bytes, signature: str | None) -> bool:
    secret = (settings.PAYSUITE_WEBHOOK_SECRET or "").encode("utf-8")
    if not secret:
        return False
    expected = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


@csrf_exempt
@require_http_methods(["GET", "POST"])
def paysuite_webhook(request):
    if request.method == "GET":
        return HttpResponse("OK", status=200)

    raw = request.body
    signature = request.headers.get("X-Webhook-Signature")

    if not _verify_signature(raw, signature):
        return HttpResponseForbidden("Invalid signature")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return HttpResponse("ok")

    event_name = payload.get("event")
    request_id = payload.get("request_id")
    data = payload.get("data") or {}

    reference = data.get("reference")
    paysuite_id = data.get("id")

    # se não vier reference, tenta variações comuns
    if not reference:
        reference = data.get("merchant_reference") or data.get("client_reference")

    if not reference and not paysuite_id:
        return HttpResponse("ok")

    with transaction.atomic():
        q = Payment.objects.select_for_update()
        payment = q.filter(reference=reference).first() if reference else None
        if not payment and paysuite_id:
            payment = q.filter(paysuite_id=paysuite_id).first()
        if not payment:
            return HttpResponse("ok")

        # idempotência
        if request_id and payment.last_webhook_request_id == request_id:
            return HttpResponse("ok")

        payment.last_webhook_request_id = request_id
        payment.raw_provider_payload = payload

        reg = payment.registration

        if event_name == "payment.success":
            tx = (data.get("transaction") or {})

            # Payment (payments app)
            payment.state = PaymentState.PAID
            payment.method = tx.get("method") or payment.method
            payment.transaction_id = tx.get("id") or tx.get("transaction_id") or payment.transaction_id

            paid_at = tx.get("paid_at") or data.get("paid_at")
            payment.paid_at = parse_datetime(paid_at) if paid_at else timezone.now()

            # Registration (events app)
            reg.payment_status = RegPaymentStatus.PAID
            reg.save(update_fields=["payment_status"])

        elif event_name == "payment.failed":
            payment.state = PaymentState.FAILED
            reg.payment_status = RegPaymentStatus.FAILED
            reg.save(update_fields=["payment_status"])

        # guarda sempre
        payment.save(update_fields=[
            "state",
            "method",
            "transaction_id",
            "paid_at",
            "last_webhook_request_id",
            "raw_provider_payload",
            "updated_at",
        ])

    return HttpResponse("ok")