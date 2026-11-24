import uuid
from datetime import timedelta

from django.db import models
from django.utils import timezone


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
    XLL = "XLL", "Extra extra Grande (XXL)"


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
    # Nome do lote na API (Geral, VIP, Early bird…): é o "tipo" do bilhete.
    price_name = models.CharField(max_length=100, blank=True)

    entered = models.BooleanField(default=False)
    qr_value = models.CharField(max_length=255, blank=True)  # QR assinado pela API
    checkout_url = models.URLField(max_length=500, blank=True)  # pagamento por cartão
    payment_instructions = models.TextField(blank=True)
    status = models.CharField(max_length=50, blank=True)
    payment_status = models.CharField(max_length=50, blank=True)
    # Convites: nota do organizador (ex.: "Patrocinador X") e quando foi enviado por e-mail.
    note = models.CharField(max_length=255, blank=True)
    invite_sent_at = models.DateTimeField(null=True, blank=True)
    # Pré-inscrição: limite para confirmar presença (expiresAt do bilhete na API).
    confirmation_deadline = models.DateTimeField(null=True, blank=True)

    buyer_phone = models.CharField(max_length=20, blank=True)
    buyer_name = models.CharField(max_length=255, blank=True)
    buyer_email = models.EmailField(blank=True)
    tamanho_camisete = models.CharField(max_length=3, choices=TamanhoCamisete.choices, default="", blank=True)

    external_created_at = models.DateTimeField(null=True, blank=True)
    external_updated_at = models.DateTimeField(null=True, blank=True)

    raw_payload = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.external_id} - {self.event_name} - {self.buyer_name}"

    @property
    def is_invite(self):
        return (self.payment_status or "").lower() == "invited"

    @property
    def ticket_type(self):
        """Tipo do bilhete, vindo da API (nome do lote) — nunca fixo no código.

        Convite: "Convite", acrescentando o lote quando não é o genérico
        (ex.: "Convite · VIP"). Bilhetes antigos, sem nome de lote
        sincronizado, ficam como "Entrada".
        """
        lote = (self.price_name or "").strip()
        if self.is_invite:
            genericos = {"", "geral", "convite"}
            return "Convite" if lote.lower() in genericos else f"Convite · {lote}"
        return lote or "Entrada"

    class Meta:
        indexes = [
            models.Index(fields=["payment_status"]),
            models.Index(fields=["event_id_external"]),
            models.Index(fields=["external_created_at"]),
            models.Index(fields=["event_name"]),
        ]


class TemporaryRegistration(models.Model):
    """Camada temporária de inscrições com limite de vagas e stock de t-shirts por tamanho."""

    STATUS_CHOICES = [
        ("open", "Aberta"),
        ("closed", "Fechada"),
        ("full", "Esgotada"),
        ("archived", "Arquivada"),
    ]

    # Identificação
    slug = models.SlugField(max_length=100, unique=True, help_text="Identificador único para o link público")
    name = models.CharField(max_length=200, help_text="Nome exibido no formulário (ex.: 'Inscrição Extra - Corrida X')")
    description = models.TextField(blank=True, help_text="Descrição exibida no formulário")

    # Associação com evento da API (para buscar preço, imagem, etc.)
    event_id_external = models.CharField(max_length=50, help_text="ID do evento na API ETickets")
    price_id_external = models.CharField(max_length=50, blank=True, help_text="ID do preço/lote na API (opcional, usa o ativo se vazio)")

    # Controle de vagas
    total_slots = models.PositiveIntegerField(default=0, help_text="Total de vagas disponíveis")
    used_slots = models.PositiveIntegerField(default=0, help_text="Vagas já preenchidas (atualizado automaticamente)")

    # Stock de t-shirts por tamanho
    shirt_stock_s = models.PositiveIntegerField(default=0, verbose_name="Stock S")
    shirt_stock_m = models.PositiveIntegerField(default=0, verbose_name="Stock M")
    shirt_stock_l = models.PositiveIntegerField(default=0, verbose_name="Stock L")
    shirt_stock_xl = models.PositiveIntegerField(default=0, verbose_name="Stock XL")
    shirt_stock_xll = models.PositiveIntegerField(default=0, verbose_name="Stock XXL")

    # Controle de tempo
    opens_at = models.DateTimeField(help_text="Quando abre as inscrições")
    closes_at = models.DateTimeField(help_text="Quando fecha as inscrições")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Status manual
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")

    # Configurações do formulário
    require_shirt_size = models.BooleanField(default=True, help_text="Exigir escolha de tamanho de t-shirt")
    require_payment = models.BooleanField(default=True, help_text="Exigir pagamento (se False, inscrição gratuita)")
    custom_success_message = models.TextField(blank=True, help_text="Mensagem personalizada após inscrição")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Inscrição Temporária"
        verbose_name_plural = "Inscrições Temporárias"
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["event_id_external"]),
            models.Index(fields=["status", "opens_at", "closes_at"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.slug})"

    @property
    def is_open(self):
        now = timezone.now()
        return (
            self.status == "open"
            and self.opens_at <= now <= self.closes_at
            and self.used_slots < self.total_slots
        )

    @property
    def is_available(self):
        """Verifica se ainda há vagas (considerando status e tempo)."""
        return self.is_open

    @property
    def remaining_slots(self):
        return max(0, self.total_slots - self.used_slots)

    def get_shirt_stock(self, size):
        """Retorna o stock disponível para um tamanho."""
        stock_map = {
            "S": self.shirt_stock_s,
            "M": self.shirt_stock_m,
            "L": self.shirt_stock_l,
            "XL": self.shirt_stock_xl,
            "XLL": self.shirt_stock_xll,
        }
        return stock_map.get(size, 0)

    def get_shirt_stock_used(self, size):
        """Retorna quantas t-shirts desse tamanho já foram reservadas."""
        return self.registrations.filter(
            tamanho_camisete=size,
            status__in=["confirmed", "pending"]
        ).count()

    def get_shirt_stock_remaining(self, size):
        total = self.get_shirt_stock(size)
        used = self.get_shirt_stock_used(size)
        return max(0, total - used)

    def is_shirt_size_available(self, size):
        return self.get_shirt_stock_remaining(size) > 0

    def get_available_shirt_sizes(self):
        """Retorna lista de tamanhos com stock disponível."""
        available = []
        for size, label in TamanhoCamisete.choices:
            if self.get_shirt_stock_remaining(size) > 0:
                available.append((size, label))
        return available

    def increment_used_slots(self):
        self.used_slots = models.F("used_slots") + 1
        self.save(update_fields=["used_slots"])
        self.refresh_from_db(fields=["used_slots"])


class TemporaryRegistrationEntry(models.Model):
    """Uma inscrição individual na camada temporária."""

    STATUS_CHOICES = [
        ("pending", "Pendente"),       # Criada, aguardando pagamento
        ("confirmed", "Confirmada"),   # Pagamento confirmado
        ("failed", "Falhou"),          # Pagamento falhou/expirou
        ("cancelled", "Cancelada"),    # Cancelada manualmente
    ]

    PAYMENT_METHOD_CHOICES = [
        ("mpesa", "M-Pesa"),
        ("emola", "e-Mola"),
        ("mkesh", "mKesh"),
    ]

    registration = models.ForeignKey(
        TemporaryRegistration,
        on_delete=models.CASCADE,
        related_name="entries"
    )

    # Dados do participante
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    tamanho_camisete = models.CharField(max_length=3, choices=TamanhoCamisete.choices, blank=True)

    # Referência de idempotência (para evitar duplicados)
    external_reference = models.CharField(max_length=64, unique=True)

    # Dados do ticket/bilhete criado na API
    external_ticket_id = models.CharField(max_length=50, blank=True)
    ticket_public_token = models.UUIDField(null=True, blank=True)

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, blank=True)
    payment_status = models.CharField(max_length=50, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Inscrição Temporária - Entrada"
        verbose_name_plural = "Inscrições Temporárias - Entradas"
        indexes = [
            models.Index(fields=["registration", "status"]),
            models.Index(fields=["external_reference"]),
            models.Index(fields=["phone"]),
            models.Index(fields=["external_ticket_id"]),
        ]

    def __str__(self):
        return f"{self.full_name} - {self.registration.name} ({self.status})"

    @property
    def is_confirmed(self):
        return self.status == "confirmed"

    @property
    def is_pending(self):
        return self.status == "pending"
