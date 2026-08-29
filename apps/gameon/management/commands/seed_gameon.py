"""
GAME ON — dados de teste.

Uso:
    python manage.py seed_gameon
    python manage.py seed_gameon --reset   # apaga dados do gameon antes de semear

Cria o catálogo completo da Tabela de Pontuação (secção 3), as 4 Cartas
Surpresa (secção 4), um punhado de participantes, DUAS edições — uma já
encerrada (com vencedores calculáveis) e a edição activa actual — e um
histórico de actividades distribuído entre as duas, em estados variados
(pendente / aprovado / rejeitado), para que o ranking, o painel de
verificação, "as minhas actividades" e o selector de edições tenham logo
conteúdo para inspeccionar.
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.gameon.models import Actividade, CartaAtribuida, CartaSurpresa, Edicao, Missao, Participante

MISSOES = [
    ("correr_5km", "Correr 5 km", Missao.Categoria.CORRIDA, 10),
    ("correr_10km", "Correr 10 km", Missao.Categoria.CORRIDA, 20),
    ("correr_antes_06h", "Correr antes das 06h00", Missao.Categoria.CORRIDA, 15),
    ("night_run", "Participar num Night Run", Missao.Categoria.CORRIDA, 15),
    ("bater_recorde", "Bater o próprio recorde", Missao.Categoria.CORRIDA, 20),
    ("agachamentos_50", "50 agachamentos", Missao.Categoria.FORCA, 5),
    ("flexoes_30", "30 flexões", Missao.Categoria.FORCA, 5),
    ("alongamento_15min", "15 min de alongamento", Missao.Categoria.FORCA, 5),
    ("correr_com_membro", "Correr com outro membro da comunidade", Missao.Categoria.COMUNIDADE, 10),
    ("levar_novo_corredor", "Levar um novo corredor para a comunidade", Missao.Categoria.COMUNIDADE, 20),
    ("publicar_treino", "Publicar o treino e marcar RunwithBroto", Missao.Categoria.COMUNIDADE, 5),
    ("3_dias_consecutivos", "Treinar 3 dias consecutivos", Missao.Categoria.CONSISTENCIA, 25),
]

CARTAS_SURPRESA = [
    (CartaSurpresa.Tipo.RELAMPAGO, "Tens 60 minutos para completar 3 km.", 15),
    (CartaSurpresa.Tipo.DUPLA, "Encontra um membro da comunidade e façam 5 km juntos.", 20),
    (CartaSurpresa.Tipo.BROTO, "5 km + 50 squats + 30 lunges.", 30),
    (CartaSurpresa.Tipo.COMUNIDADE, "Incentiva 3 corredores a completarem o treino do dia.", 15),
]

PARTICIPANTES = [
    ("Yuran Saraiva", "+258844723840"),
    ("Amina Cassamo", "+258821234567"),
    ("Bruno Tembe", "+258849876543"),
    ("Célia Nhantumbo", "+258862345678"),
    ("Dércio Machava", "+258873456789"),
    ("Elsa Chissano", "+258841122334"),
    ("Faruk Ibraimo", "+258829988776"),
    ("Graça Muianga", "+258855667788"),
]

ESTADOS_DISTRIBUICAO = (
    [Actividade.Estado.APROVADO] * 6
    + [Actividade.Estado.PENDENTE] * 3
    + [Actividade.Estado.REJEITADO] * 1
)

MOTIVOS_REJEICAO = [
    "Evidência ilegível, por favor reenvia.",
    "Distância não confere com o registado.",
    "Sem confirmação da equipa para esta missão.",
]


class Command(BaseCommand):
    help = "Gera dados de teste para o GAME ON: edições, missões, cartas surpresa, participantes e actividades."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Apaga todos os dados do gameon (Actividade, Edicao, Participante, CartaSurpresa, Missao) antes de semear.",
        )
        parser.add_argument(
            "--actividades-por-participante",
            type=int,
            default=8,
            help="Número de actividades a gerar por participante, repartidas pelas duas edições (default: 8).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            self.stdout.write("A apagar dados existentes do gameon...")
            Actividade.objects.all().delete()
            CartaAtribuida.objects.all().delete()
            Participante.objects.all().delete()
            CartaSurpresa.objects.all().delete()
            Missao.objects.all().delete()
            Edicao.objects.all().delete()

        missoes = self._seed_missoes()
        cartas = self._seed_cartas_surpresa()
        edicao_anterior, edicao_atual = self._seed_edicoes()
        participantes = self._seed_participantes()
        self._seed_cartas_atribuidas(participantes, cartas)
        self._seed_actividades(
            participantes, missoes, edicao_anterior, edicao_atual, options["actividades_por_participante"]
        )

        for participante in participantes:
            participante.recalcular_pontos_totais()

        self.stdout.write(self.style.SUCCESS(
            f"OK: 2 edições ({edicao_anterior.nome} — encerrada, {edicao_atual.nome} — activa), "
            f"{len(missoes)} missões, {len(cartas)} cartas surpresa, "
            f"{len(participantes)} participantes, "
            f"{Actividade.objects.count()} actividades."
        ))

    def _seed_missoes(self):
        missoes = []
        for chave, nome, categoria, pontos in MISSOES:
            missao, _ = Missao.objects.update_or_create(
                chave=chave, defaults={"nome": nome, "categoria": categoria, "pontos": pontos, "activa": True}
            )
            missoes.append(missao)
        self.stdout.write(f"Missões: {len(missoes)}")
        return missoes

    def _seed_cartas_surpresa(self):
        cartas = []
        agora = timezone.now()
        for i, (tipo, descricao, pontos) in enumerate(CARTAS_SURPRESA):
            carta, _ = CartaSurpresa.objects.update_or_create(
                tipo=tipo, descricao=descricao,
                defaults={"pontos": pontos, "data_lancamento": agora - timedelta(days=i), "activa": True},
            )
            cartas.append(carta)
        self.stdout.write(f"Cartas Surpresa: {len(cartas)}")
        return cartas

    def _seed_edicoes(self):
        """
        Duas edições de 14 dias, encostadas: uma já terminou (para testar
        o ranking histórico e os vencedores), a outra está a decorrer agora.
        """
        hoje = timezone.now().date()

        edicao_anterior, _ = Edicao.objects.update_or_create(
            nome="GAME ON — Edição 1",
            defaults={
                "data_inicio": hoje - timedelta(days=28),
                "data_fim_prevista": hoje - timedelta(days=14),
                "estado": Edicao.Estado.ENCERRADA,
                "encerrada_em": timezone.now() - timedelta(days=14),
            },
        )
        edicao_atual, _ = Edicao.objects.update_or_create(
            nome="GAME ON — Edição 2",
            defaults={
                "data_inicio": hoje - timedelta(days=13),
                "data_fim_prevista": hoje + timedelta(days=1),
                "estado": Edicao.Estado.ATIVA,
            },
        )
        self.stdout.write(f"Edições: {edicao_anterior.nome} (encerrada), {edicao_atual.nome} (activa)")
        return edicao_anterior, edicao_atual

    def _seed_participantes(self):
        participantes = []
        for nome, telefone in PARTICIPANTES:
            participante, _ = Participante.objects.get_or_create(telefone=telefone, defaults={"nome": nome})
            participantes.append(participante)
        self.stdout.write(f"Participantes: {len(participantes)}")
        return participantes

    def _seed_cartas_atribuidas(self, participantes, cartas):
        """
        Simula o comando atribuir_cartas_surpresa: só uma parte dos
        participantes recebe uma carta, e cada um recebe uma ao acaso —
        não é "todos recebem tudo todos os dias".
        """
        contemplados = random.sample(participantes, k=max(1, round(len(participantes) * 0.5)))
        criadas = 0
        for participante in contemplados:
            carta = random.choice(cartas)
            _, criada = CartaAtribuida.objects.get_or_create(participante=participante, carta=carta)
            if criada:
                criadas += 1
        self.stdout.write(f"Cartas atribuídas: {criadas} (a {len(contemplados)} participante(s))")

    def _seed_actividades(self, participantes, missoes, edicao_anterior, edicao_atual, n_por_participante):
        hoje = timezone.now().date()
        criadas = 0
        for participante in participantes:
            cartas_disponiveis = list(participante.cartas_atribuidas.filter(usada=False))

            for _ in range(n_por_participante):
                dias_atras = random.randint(0, 27)  # cobre as duas edições de 14 dias
                edicao = edicao_atual if dias_atras <= 13 else edicao_anterior

                # Só usa uma carta surpresa se o participante realmente tiver
                # uma atribuída e por usar, e só na edição activa (as cartas
                # atribuídas foram criadas "agora", não fazem sentido na edição antiga).
                if edicao is edicao_atual and cartas_disponiveis and random.random() < 0.3:
                    atribuicao = cartas_disponiveis.pop()
                    origem, campo = atribuicao.carta, "carta_surpresa"
                else:
                    atribuicao = None
                    origem, campo = random.choice(missoes), "missao"

                estado = random.choice(ESTADOS_DISTRIBUICAO)

                actividade = Actividade(
                    participante=participante,
                    edicao=edicao,
                    pontos=origem.pontos,
                    estado=estado,
                    data_actividade=hoje - timedelta(days=dias_atras),
                    evidencia_url="https://www.strava.com/activities/exemplo",
                )
                setattr(actividade, campo, origem)

                if estado == Actividade.Estado.REJEITADO:
                    actividade.nota_organizacao = random.choice(MOTIVOS_REJEICAO)
                if estado != Actividade.Estado.PENDENTE:
                    actividade.revisado_em = timezone.now() - timedelta(days=max(dias_atras - 1, 0))

                actividade.save()

                if atribuicao is not None:
                    # Rejeitado liberta a carta (mesma regra do Actividade.rejeitar);
                    # pendente/aprovado marca-a como usada.
                    atribuicao.usada = estado != Actividade.Estado.REJEITADO
                    atribuicao.save(update_fields=["usada"])

                criadas += 1
        self.stdout.write(f"Actividades: {criadas}")