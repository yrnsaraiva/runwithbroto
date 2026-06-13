from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User


class Perfil(models.Model):

    class Genero(models.TextChoices):
        MASCULINO = "masculino", "Masculino"
        FEMININO = "feminino",  "Feminino"
        OUTRO = "outro",     "Outro"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="perfil")
    phone = models.CharField(max_length=20, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=20, choices=Genero.choices, blank=True)

    def __str__(self):
        return self.user.username


class Plano(models.Model):
    """Define os tipos de assinatura disponíveis."""
    nome = models.CharField(max_length=100, unique=True)
    descricao = models.TextField(blank=True)
    preco = models.DecimalField(max_digits=10, decimal_places=2)
    duracao_dias = models.PositiveIntegerField()
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nome} — {self.preco} MZN / {self.duracao_dias}d"

    class Meta:
        verbose_name = "Plano"
        verbose_name_plural = "Planos"
        ordering = ["preco"]


class Assinatura(models.Model):
    """Liga o utilizador ao plano — histórico completo de memberships."""

    class Estado(models.TextChoices):
        ACTIVA = "activa",    "Activa"
        EXPIRADA = "expirada",  "Expirada"
        CANCELADA = "cancelada", "Cancelada"
        SUSPENSA = "suspensa",  "Suspensa"

    usuario = models.ForeignKey(User, on_delete=models.PROTECT, related_name="assinaturas")
    plano = models.ForeignKey(Plano, on_delete=models.PROTECT, related_name="assinaturas")
    data_inicio = models.DateField(default=timezone.now)
    data_fim = models.DateField()
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.ACTIVA)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def dias_restantes(self):
        return max((self.data_fim - timezone.now().date()).days, 0)

    @property
    def esta_activa(self):
        return self.estado == self.Estado.ACTIVA and self.data_fim >= timezone.now().date()

    def expirar(self):
        self.estado = self.Estado.EXPIRADA
        self.save(update_fields=["estado"])

    def cancelar(self):
        self.estado = self.Estado.CANCELADA
        self.save(update_fields=["estado"])

    def __str__(self):
        return f"{self.usuario.nome_completo} · {self.plano.nome} ({self.estado})"

    class Meta:
        verbose_name = "Assinatura"
        verbose_name_plural = "Assinaturas"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["usuario", "estado"]),
            models.Index(fields=["data_fim"]),
        ]


class Pagamento(models.Model):
    """Pagamento associado a uma assinatura."""

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        PAGO = "pago", "Pago"
        FALHOU = "falhou", "Falhou"
        REEMBOLSADO = "reembolsado", "Reembolsado"

    assinatura = models.ForeignKey(Assinatura, on_delete=models.PROTECT, related_name="pagamentos")
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDENTE)
    referencia_externa = models.CharField(max_length=255, blank=True)
    pago_em = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def marcar_como_pago(self, referencia: str = ""):
        self.status = self.Status.PAGO
        self.pago_em = timezone.now()
        if referencia:
            self.referencia_externa = referencia
        self.save(update_fields=["status", "pago_em", "referencia_externa"])

    def reembolsar(self):
        self.status = self.Status.REEMBOLSADO
        self.save(update_fields=["status"])

    def __str__(self):
        return f"{self.assinatura.usuario.nome_completo} · {self.valor} MZN · {self.status}"

    class Meta:
        verbose_name = "Pagamento"
        verbose_name_plural = "Pagamentos"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["assinatura", "status"]),
            models.Index(fields=["pago_em"]),
        ]