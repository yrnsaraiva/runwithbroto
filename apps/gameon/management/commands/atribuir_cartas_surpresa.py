"""
GAME ON — atribuição de Cartas Surpresa.

Não é um job diário: corre-se quando o Coach Broto quiser lançar uma ronda
de cartas (secção 4 do regulamento diz "em dias aleatórios" — quem decide
o dia és tu, correndo este comando quando quiseres).

Uso:
    python manage.py atribuir_cartas_surpresa                    # ~30% dos participantes, carta ao acaso
    python manage.py atribuir_cartas_surpresa --quantidade 5      # exactamente 5 participantes
    python manage.py atribuir_cartas_surpresa --percentagem 0.5   # 50% dos participantes
    python manage.py atribuir_cartas_surpresa --tipo relampago    # só atribui Missão Relâmpago
"""
import random

from django.core.management.base import BaseCommand, CommandError

from apps.gameon.models import CartaAtribuida, CartaSurpresa, Participante


class Command(BaseCommand):
    help = "Atribui uma Carta Surpresa a um subconjunto aleatório de participantes."

    def add_arguments(self, parser):
        parser.add_argument("--quantidade", type=int, help="Número exacto de participantes a contemplar.")
        parser.add_argument(
            "--percentagem", type=float, default=0.3,
            help="Fracção dos participantes a contemplar quando --quantidade não é indicado (default: 0.3).",
        )
        parser.add_argument(
            "--tipo", choices=[c[0] for c in CartaSurpresa.Tipo.choices],
            help="Restringe a atribuição a um tipo de carta específico. Sem isto, escolhe ao acaso entre as activas.",
        )

    def handle(self, *args, **options):
        cartas_activas = list(CartaSurpresa.objects.filter(activa=True))
        if options["tipo"]:
            cartas_activas = [c for c in cartas_activas if c.tipo == options["tipo"]]
        if not cartas_activas:
            raise CommandError("Não há Cartas Surpresa activas (ou nenhuma do tipo indicado) para atribuir.")

        participantes = list(Participante.objects.all())
        if not participantes:
            raise CommandError("Não há participantes registados.")

        if options["quantidade"]:
            n = min(options["quantidade"], len(participantes))
        else:
            n = max(1, round(len(participantes) * options["percentagem"]))

        escolhidos = random.sample(participantes, n)

        criadas, ja_tinham = 0, 0
        for participante in escolhidos:
            carta = random.choice(cartas_activas)
            _, criada = CartaAtribuida.objects.get_or_create(participante=participante, carta=carta)
            if criada:
                criadas += 1
            else:
                ja_tinham += 1

        self.stdout.write(self.style.SUCCESS(
            f"OK: {criadas} carta(s) nova(s) atribuída(s) a {len(escolhidos)} participante(s) "
            f"({ja_tinham} já tinham essa carta)."
        ))
