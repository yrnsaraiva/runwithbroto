from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.core.validators import RegexValidator
from decimal import Decimal
from django.core.validators import MinValueValidator
import secrets
import string


def generate_ticket_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem O, 0, I, 1
    return "RWB-" + "".join(secrets.choice(alphabet) for _ in range(8))


class City(models.TextChoices):
    MAPUTO = "MAPUTO", "Maputo"
    MATOLA = "MATOLA", "Matola"


class EventType(models.TextChoices):
    WEEKLY = "WEEKLY", "Weekly Run"
    LONG = "LONG", "Long Run"
    COLLAB = "COLLAB", "Collab"


class Event(models.Model):
    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=240, unique=True, db_index=True, blank=True)

    city = models.CharField(max_length=20, choices=City.choices, db_index=True)
    event_type = models.CharField(max_length=20, choices=EventType.choices, db_index=True)

    start_at = models.DateTimeField(db_index=True)

    meeting_point = models.CharField(max_length=220)

    distance_min_km = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)

    description = models.TextField(blank=True)

    price = models.DecimalField(
        "Preço do ticket (MZN)",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Deixe vazio para evento free. Ex: 500.00",
        db_index=True,
    )

    capacity = models.PositiveIntegerField(default=150)

    is_published = models.BooleanField(default=True, db_index=True)

    poster = models.ImageField(upload_to="events/posters/", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("start_at",)
        indexes = [
            models.Index(fields=["city", "start_at"]),
            models.Index(fields=["event_type", "start_at"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_city_display()})"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:200] or "event"
            slug = base
            i = 2
            while Event.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def is_upcoming(self):
        return self.start_at >= timezone.now()

    @property
    def is_free(self) -> bool:
        return self.price in (None, Decimal("0.00"))

    @property
    def ticket_price_display(self) -> str:
        if self.is_free:
            return "Free"
        return f"{self.price:.2f} MZN"

    @property
    def registrations_count(self) -> int:
        return self.registrations.exclude(status=RegistrationStatus.CANCELLED).count()

    @property
    def is_sold_out(self) -> bool:
        return self.registrations_count >= self.capacity


phone_validator = RegexValidator(
    regex=r"^\+?\d{7,15}$",
    message="Informe um número válido (ex: 84xxxxxxx ou +25884xxxxxxx)."
)


class PaymentStatus(models.TextChoices):
    UNPAID = "UNPAID", "Unpaid"
    PENDING = "PENDING", "Pending"
    PAID = "PAID", "Paid"
    FAILED = "FAILED", "Failed"
    REFUNDED = "REFUNDED", "Refunded"


class RegistrationStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CANCELLED = "cancelled", "Cancelled"


class EventRegistration(models.Model):

    ticket_code = models.CharField(
        max_length=15,
        unique=True,
        editable=False
    )

    event = models.ForeignKey("Event", on_delete=models.PROTECT, related_name="registrations")

    # pessoa / ingresso (1:1)
    full_name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=20, validators=[phone_validator], blank=True)

    status = models.CharField(
        max_length=20,
        choices=RegistrationStatus.choices,
        default=RegistrationStatus.ACTIVE
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
        db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["event", "payment_status"]),
            models.Index(fields=["phone"]),
        ]
        constraints = [
            # impede 2 pedidos pagos/pendentes para o MESMO email no MESMO evento
            models.UniqueConstraint(fields=["event", "email"], name="uniq_order_event_email"),
        ]

    def __str__(self):
        return f"{self.ticket_code} • {self.full_name} • {self.status}"

    def save(self, *args, **kwargs):
        if not self.ticket_code:
            while True:
                code = generate_ticket_code()
                if not EventRegistration.objects.filter(ticket_code=code).exists():
                    self.ticket_code = code
                    break
        super().save(*args, **kwargs)

    @property
    def amount_due(self):
        return self.event.price if self.status == RegistrationStatus.ACTIVE else 0

