from django.db import models
from django.core.validators import RegexValidator
from events.models import EventRegistration


alnum_ref_validator = RegexValidator(
    regex=r"^[A-Za-z0-9]+$",
    message="Reference deve conter apenas letras e números."
)


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PAID = "PAID", "Paid"
    FAILED = "FAILED", "Failed"


class PaymentMethod(models.TextChoices):
    MPESA = "mpesa", "M-Pesa"
    EMOLA = "emola", "e-Mola"
    CARD = "card", "Card"


class Payment(models.Model):
    registration = models.OneToOneField(
        EventRegistration,
        on_delete=models.PROTECT,
        related_name="payment",
    )

    reference = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        validators=[alnum_ref_validator],
    )

    paysuite_id = models.CharField(max_length=80, blank=True, null=True, db_index=True)
    checkout_url = models.URLField(blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True,
    )

    method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        blank=True,
        null=True,
        db_index=True,
    )

    transaction_id = models.CharField(max_length=120, blank=True, null=True, db_index=True)
    paid_at = models.DateTimeField(blank=True, null=True)

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="MZN")

    raw_provider_payload = models.JSONField(blank=True, null=True)
    last_webhook_request_id = models.CharField(max_length=120, blank=True, null=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.reference} • {self.status}"