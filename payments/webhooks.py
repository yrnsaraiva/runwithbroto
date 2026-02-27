import json
import hmac
import hashlib

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, HttpResponseForbidden
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Payment, PaymentStatus


def _verify_signature(raw: bytes, signature: str | None) -> bool:
    if not settings.PAYSUITE_WEBHOOK_SECRET:
        return False
    secret = settings.PAYSUITE_WEBHOOK_SECRET.encode("utf-8")
    expected = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


@csrf_exempt
@require_POST
def paysuite_webhook(request):
    raw = request.body
    signature = request.headers.get("X-Webhook-Signature")

    if not _verify_signature(raw, signature):
        return HttpResponseForbidden("Invalid signature")

    event = json.loads(raw.decode("utf-8"))
    event_name = event.get("event")
    request_id = event.get("request_id")
    data = event.get("data") or {}

    reference = data.get("reference")
    paysuite_id = data.get("id")

    if not reference and not paysuite_id:
        return HttpResponse("ok")

    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(reference=reference).first()
        if not payment and paysuite_id:
            payment = Payment.objects.select_for_update().filter(paysuite_id=paysuite_id).first()
        if not payment:
            return HttpResponse("ok")

        # idempotência
        if request_id and payment.last_webhook_request_id == request_id:
            return HttpResponse("ok")

        payment.last_webhook_request_id = request_id
        payment.raw_provider_payload = event

        reg = payment.registration  # OneToOne

        if event_name == "payment.success":
            tx = (data.get("transaction") or {})
            payment.status = PaymentStatus.PAID
            payment.method = tx.get("method") or payment.method
            payment.transaction_id = tx.get("id") or tx.get("transaction_id") or payment.transaction_id

            paid_at = tx.get("paid_at")
            payment.paid_at = parse_datetime(paid_at) if paid_at else timezone.now()

            # Atualiza inscrição
            reg.payment_status = PaymentStatus.PAID
            reg.save(update_fields=["payment_status"])

        elif event_name == "payment.failed":
            payment.status = PaymentStatus.FAILED
            reg.payment_status = PaymentStatus.FAILED
            reg.save(update_fields=["payment_status"])

        # eventos desconhecidos: só guarda payload
        payment.save(update_fields=[
            "status", "method", "transaction_id", "paid_at",
            "last_webhook_request_id", "raw_provider_payload", "updated_at"
        ])

    return HttpResponse("ok")