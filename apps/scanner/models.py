from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class CheckInLog(models.Model):
    """
    Regista cada tentativa de check-in (sucesso ou falha).
    Útil para auditoria e para saber quem fez o check-in de quem.
    """

    class Result(models.TextChoices):
        OK = "ok", "Entrada autorizada"
        ALREADY_ENTERED = "already_entered", "Já tinha entrado"
        NOT_PAID = "not_paid", "Pagamento pendente"
        NOT_FOUND = "not_found", "Ticket não encontrado"
        INVALID_QR = "invalid_qr", "QR inválido"

    ticket_external_id = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name="ID do ticket",
    )
    result = models.CharField(
        max_length=20,
        choices=Result.choices,
        verbose_name="Resultado",
    )
    scanned_by = models.ForeignKey(
        User,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="Scaneado por",
    )
    scanned_at = models.DateTimeField(auto_now_add=True, verbose_name="Data/hora")
    raw_qr = models.CharField(max_length=255, blank=True, verbose_name="QR lido")

    class Meta:
        ordering = ["-scanned_at"]
        verbose_name = "Log de Check-in"
        verbose_name_plural = "Logs de Check-in"

    def __str__(self):
        return f"{self.ticket_external_id} — {self.get_result_display()} — {self.scanned_at:%d/%m/%Y %H:%M}"
