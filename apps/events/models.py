import uuid

from django.db import models


class Provincia(models.TextChoices):
    MAPUTO_CIDADE = "MAPUTO_CIDADE", "Maputo Cidade"
    MAPUTO_PROVINCIA = "MAPUTO_PROVINCIA", "Maputo Província"
    GAZA = "GAZA", "Gaza"
    INHAMBANE = "INHAMBANE", "Inhambane"
    SOFALA = "SOFALA", "Sofala"
    MANICA = "MANICA", "Manica"
    TETE = "TETE", "Tete"
    ZAMBEZIA = "ZAMBEZIA", "Zambézia"
    NAMPULA = "NAMPULA", "Nampula"
    CABO_DELGADO = "CABO_DELGADO", "Cabo Delgado"
    NIASSA = "NIASSA", "Niassa"


class TamanhoCamisete(models.TextChoices):
    S = "S", "Pequeno (S)"
    M = "M", "Médio (M)"
    L = "L", "Grande (L)"
    XL = "XL", "Extra Grande (XL)"


class ExternalTicket(models.Model):
    external_id = models.CharField(max_length=50, unique=True)
    # Token não adivinhável usado nos links públicos (sucesso / download do PDF).
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    event_id_external = models.CharField(max_length=50)
    event_name = models.CharField(max_length=255)
    event_category = models.CharField(max_length=100, blank=True)

    event_province = models.CharField(max_length=100, blank=True)
    event_location_details = models.CharField(max_length=255, blank=True)
    event_image_url = models.URLField(blank=True)
    event_date = models.DateTimeField(null=True, blank=True)

    price_id_external = models.CharField(max_length=50, blank=True)
    price_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    entered = models.BooleanField(default=False)
    qr_value = models.CharField(max_length=255, blank=True)  # QR assinado pela API
    checkout_url = models.URLField(max_length=500, blank=True)  # pagamento por cartão
    payment_instructions = models.TextField(blank=True)
    status = models.CharField(max_length=50, blank=True)
    payment_status = models.CharField(max_length=50, blank=True)
    # Pré-inscrição: limite para confirmar presença (expiresAt do bilhete na API).
    confirmation_deadline = models.DateTimeField(null=True, blank=True)

    buyer_phone = models.CharField(max_length=20, blank=True)
    buyer_name = models.CharField(max_length=255, blank=True)
    buyer_email = models.EmailField(blank=True)
    tamanho_camisete = models.CharField(max_length=3, choices=TamanhoCamisete.choices, default=TamanhoCamisete.M, blank=True)

    external_created_at = models.DateTimeField(null=True, blank=True)
    external_updated_at = models.DateTimeField(null=True, blank=True)

    raw_payload = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.external_id} - {self.event_name} - {self.buyer_name}"

    class Meta:
        indexes = [
            models.Index(fields=["payment_status"]),
            models.Index(fields=["event_id_external"]),
            models.Index(fields=["external_created_at"]),
            models.Index(fields=["event_name"]),
        ]
