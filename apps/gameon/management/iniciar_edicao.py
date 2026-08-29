"""
GAME ON — abrir uma nova edição.

Como as edições são periódicas (secção 8: 14 dias, podendo tornar-se
mensal), este comando é o atalho para reabrir o jogo. Encerra
automaticamente qualquer edição ainda activa — reflecte a mesma regra
que já está em Edicao.save() — por isso nunca ficam duas activas ao
mesmo tempo.

Uso:
    python manage.py iniciar_edicao --nome "GAME ON — Edição 2"
    python manage.py iniciar_edicao --nome "GAME ON — Edição 3" --dias 30
"""
import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.gameon.models import Edicao


class Command(BaseCommand):
    help = "Abre uma nova edição do GAME ON, encerrando automaticamente a anterior se estiver activa."

    def add_arguments(self, parser):
        parser.add_argument("--nome", required=True, help='Ex.: "GAME ON — Edição 2"')
        parser.add_argument(
            "--dias", type=int, default=14,
            help="Duração prevista em dias (default: 14, formato sugerido na secção 8 do regulamento).",
        )

    def handle(self, *args, **options):
        anterior = Edicao.atual()
        hoje = timezone.now().date()

        edicao = Edicao.objects.create(
            nome=options["nome"],
            data_inicio=hoje,
            data_fim_prevista=hoje + datetime.timedelta(days=options["dias"]),
            estado=Edicao.Estado.ATIVA,
        )

        if anterior:
            self.stdout.write(f"Edição anterior encerrada automaticamente: {anterior.nome}")
        self.stdout.write(self.style.SUCCESS(
            f"Nova edição activa: {edicao.nome} ({edicao.data_inicio} → {edicao.data_fim_prevista})"
        ))
