from django.db import models
from django.utils import timezone


class PaymentStatus(models.TextChoices):
    UNPAID = "UNPAID", "Unpaid"
    PENDING = "PENDING", "Pending"
    PAID = "PAID", "Paid"
    FAILED = "FAILED", "Failed"
    REFUNDED = "REFUNDED", "Refunded"


class Payment(models.Model):
    """
    1 pagamento PaySuite por inscrição (padrão recomendado).
    """
    registration = models.OneToOneField(
        "events.EventRegistration",
        on_delete=models.CASCADE,
        related_name="payment",
    )

    # referência única do teu sistema (vai pro PaySuite)
    reference = models.CharField(max_length=50, unique=True)

    amount = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)

    # PaySuite
    paysuite_id = models.CharField(max_length=64, blank=True, null=True)  # uuid no provider
    checkout_url = models.URLField(blank=True, null=True)

    method = models.CharField(max_length=40, blank=True, null=True)
    transaction_id = models.CharField(max_length=64, blank=True, null=True)
    paid_at = models.DateTimeField(blank=True, null=True)

    # idempotência do webhook
    last_webhook_request_id = models.CharField(max_length=64, blank=True, null=True)

    raw_provider_payload = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def mark_paid(self, *, method=None, transaction_id=None, paid_at=None, payload=None):
        self.status = PaymentStatus.PAID
        self.method = method or self.method
        self.transaction_id = transaction_id or self.transaction_id
        self.paid_at = paid_at or timezone.now()
        if payload is not None:
            self.raw_provider_payload = payload
        self.save(update_fields=["status", "method", "transaction_id", "paid_at", "raw_provider_payload", "updated_at"])