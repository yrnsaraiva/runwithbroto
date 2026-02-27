import json
import hmac
import hashlib
import logging

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, HttpResponseForbidden
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Payment, PaymentStatus as PayPaymentStatus
from events.models import PaymentStatus as RegPaymentStatus

logger = logging.getLogger(__name__)


def _verify_signature(raw: bytes, signature: str | None) -> bool:
    secret = (settings.PAYSUITE_WEBHOOK_SECRET or "").encode("utf-8")
    if not secret:
        return False
    expected = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def _tx_status(payload_data: dict) -> str:
    tx = (payload_data.get("transaction") or {})
    return (tx.get("status") or "").lower()


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

    logger.info(
        "PaySuite webhook: event=%s request_id=%s reference=%s paysuite_id=%s tx_status=%s",
        event_name, request_id, reference, paysuite_id, _tx_status(data)
    )

    if not reference and not paysuite_id:
        return HttpResponse("ok")

    with transaction.atomic():
        q = Payment.objects.select_for_update()
        payment = q.filter(reference=reference).first() if reference else None
        if not payment and paysuite_id:
            payment = q.filter(paysuite_id=paysuite_id).first()

        if not payment:
            logger.warning("Webhook payment not found: reference=%s paysuite_id=%s payload=%s", reference, paysuite_id, payload)
            return HttpResponse("ok")

        if request_id and payment.last_webhook_request_id == request_id:
            return HttpResponse("ok")

        payment.last_webhook_request_id = request_id
        payment.raw_provider_payload = payload

        reg = payment.registration

        # Critério de sucesso: event_name OU transaction.status
        tx = (data.get("transaction") or {})
        tx_status = (tx.get("status") or "").lower()

        is_paid = (event_name == "payment.success") or (tx_status == "completed")
        is_failed = (event_name == "payment.failed") or (tx_status in ("failed", "cancelled", "canceled"))

        if is_paid:
            payment.status = PayPaymentStatus.PAID
            payment.transaction_id = str(tx.get("id") or tx.get("transaction_id") or payment.transaction_id)

            paid_at = tx.get("paid_at") or data.get("paid_at")
            payment.paid_at = parse_datetime(paid_at) if paid_at else timezone.now()

            reg.payment_status = RegPaymentStatus.PAID
            reg.save(update_fields=["payment_status"])

        elif is_failed:
            payment.status = PayPaymentStatus.FAILED

            reg.payment_status = RegPaymentStatus.FAILED
            reg.save(update_fields=["payment_status"])

        payment.save(update_fields=[
            "status",
            "transaction_id",
            "paid_at",
            "last_webhook_request_id",
            "raw_provider_payload",
            "updated_at",
        ])

    return HttpResponse("ok")