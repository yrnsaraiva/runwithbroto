"""
GAME ON — RunWithBroto
Modelos da app gameon.

Princípio central: nunca guardamos um "total de pontos" editável directamente.
Cada actividade aprovada é uma linha no ledger (Actividade); o total de um
participante é sempre derivado por soma, o que dá auditoria completa e
resolve os critérios de desempate sem estruturas extra.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Edicao(models.Model):
    """
    Um período de jogo (secção 8 do regulamento: 14 dias sugeridos, podendo
    tornar-se mensal). Cada Actividade pertence a uma Edição; encerrar uma
    edição congela os pontos e os vencedores dessa ronda, sem apagar nada —
    a próxima edição começa do zero, mas o histórico fica sempre consultável.
    """

    class Estado(models.TextChoices):
        ATIVA = "activa", "Activa"
        ENCERRADA = "encerrada", "Encerrada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nome = models.CharField(max_length=120, help_text="Ex.: GAME ON — Edição 1")
    data_inicio = models.DateField()
    data_fim_prevista = models.DateField(help_text="Duração sugerida: 14 dias (secção 8 do regulamento)")
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.ATIVA)
    encerrada_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Edição"
        verbose_name_plural = "Edições"
        ordering = ["-data_inicio"]

    def __str__(self):
        return f"{self.nome} ({self.get_estado_display()})"

    def save(self, *args, **kwargs):
        if self.estado == self.Estado.ATIVA:
            # Só pode haver uma edição activa de cada vez: activar esta
            # encerra automaticamente qualquer outra que ainda o estivesse.
            Edicao.objects.filter(estado=self.Estado.ATIVA).exclude(pk=self.pk).update(
                estado=self.Estado.ENCERRADA, encerrada_em=timezone.now()
            )
        super().save(*args, **kwargs)

    def encerrar(self):
        self.estado = self.Estado.ENCERRADA
        self.encerrada_em = timezone.now()
        self.save(update_fields=["estado", "encerrada_em"])

    @classmethod
    def atual(cls):
        """A edição activa neste momento, ou None se nenhuma estiver aberta."""
        return cls.objects.filter(estado=cls.Estado.ATIVA).first()


class Missao(models.Model):
    """Catálogo fixo de desafios da Tabela de Pontuação (secção 3 do regulamento)."""

    class Categoria(models.TextChoices):
        CORRIDA = "corrida", "Corrida"
        FORCA = "forca", "Força"
        CONSISTENCIA = "consistencia", "Consistência"
        COMUNIDADE = "comunidade", "Comunidade"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chave = models.SlugField(unique=True, help_text="Identificador interno, ex.: correr_5km")
    nome = models.CharField(max_length=120)
    categoria = models.CharField(max_length=20, choices=Categoria.choices)
    pontos = models.PositiveIntegerField(help_text="Pontos actuais da missão (pode ser ajustado pela organização)")
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Missão"
        verbose_name_plural = "Missões"
        ordering = ["categoria", "nome"]

    def __str__(self):
        return f"{self.nome} ({self.pontos} pts)"


class CartaSurpresa(models.Model):
    """Missões especiais lançadas pelo Coach Broto (secção 4 do regulamento)."""

    class Tipo(models.TextChoices):
        RELAMPAGO = "relampago", "Missão Relâmpago"
        DUPLA = "dupla", "Missão Dupla"
        BROTO = "broto", "Missão Broto"
        COMUNIDADE = "comunidade", "Missão Comunidade"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    descricao = models.CharField(max_length=255)
    pontos = models.PositiveIntegerField()
    data_lancamento = models.DateTimeField(default=timezone.now)
    activa = models.BooleanField(
        default=True, help_text="Desactiva automaticamente quando a organização encerra a carta"
    )

    class Meta:
        verbose_name = "Carta Surpresa"
        verbose_name_plural = "Cartas Surpresa"
        ordering = ["-data_lancamento"]

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.descricao[:40]}"


class CartaAtribuida(models.Model):
    """
    Atribuição de uma Carta Surpresa a um participante específico.
    Não é a organização que decide quem recebe cada carta em cada dia — o
    management command `atribuir_cartas_surpresa` escolhe participantes ao
    acaso e dá-lhes uma carta activa. Não precisa de correr todos os dias:
    corre quando o Coach Broto quiser lançar uma ronda.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    participante = models.ForeignKey(
        "Participante", on_delete=models.CASCADE, related_name="cartas_atribuidas"
    )
    carta = models.ForeignKey(CartaSurpresa, on_delete=models.CASCADE, related_name="atribuicoes")
    atribuida_em = models.DateTimeField(auto_now_add=True)
    usada = models.BooleanField(
        default=False,
        help_text="Marcada automaticamente quando o participante regista uma actividade com esta carta.",
    )

    class Meta:
        verbose_name = "Carta Atribuída"
        verbose_name_plural = "Cartas Atribuídas"
        ordering = ["-atribuida_em"]
        constraints = [
            models.UniqueConstraint(fields=["participante", "carta"], name="carta_atribuida_unica_por_participante")
        ]

    def __str__(self):
        estado = "usada" if self.usada else "disponível"
        return f"{self.participante} — {self.carta} ({estado})"


class Participante(models.Model):
    """Um inscrito no desafio. Liga-se ao utilizador da plataforma RWB, se existir."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilizador = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="participante_gameon",
        null=True, blank=True,
    )
    nome = models.CharField(max_length=150)
    telefone = models.CharField(
        max_length=30, unique=True,
        help_text="Identifica o participante nas páginas públicas — sem conta nem password.",
    )
    inscrito_em = models.DateTimeField(auto_now_add=True)

    # Campo desnormalizado só para performance nas listagens de ranking.
    # Nunca escrever directamente aqui — usar recalcular_pontos_totais().
    pontos_totais_cache = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        verbose_name = "Participante"
        verbose_name_plural = "Participantes"
        ordering = ["-pontos_totais_cache", "nome"]

    def __str__(self):
        return self.nome

    def recalcular_pontos_totais(self):
        total = self.actividades.filter(estado=Actividade.Estado.APROVADO).aggregate(
            total=models.Sum("pontos")
        )["total"] or 0
        Participante.objects.filter(pk=self.pk).update(pontos_totais_cache=total)
        self.pontos_totais_cache = total
        return total

    def numero_desafios_concluidos(self):
        """Usado como 1º critério de desempate (regra 7)."""
        return self.actividades.filter(estado=Actividade.Estado.APROVADO).count()


class Actividade(models.Model):
    """
    Uma submissão de um participante — o ledger do jogo.
    `pontos` é uma cópia (snapshot) do valor da missão/carta no momento do
    registo, para que ajustes futuros à pontuação (regra 7) não alterem
    actividades já aprovadas.
    """

    class Estado(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        APROVADO = "aprovado", "Aprovado"
        REJEITADO = "rejeitado", "Rejeitado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    participante = models.ForeignKey(Participante, on_delete=models.CASCADE, related_name="actividades")
    edicao = models.ForeignKey(
        Edicao, on_delete=models.PROTECT, null=True, blank=True, related_name="actividades",
        help_text="Atribuída automaticamente à edição activa no momento do registo.",
    )

    missao = models.ForeignKey(Missao, on_delete=models.PROTECT, null=True, blank=True, related_name="actividades")
    carta_surpresa = models.ForeignKey(
        CartaSurpresa, on_delete=models.PROTECT, null=True, blank=True, related_name="actividades"
    )

    pontos = models.PositiveIntegerField(help_text="Snapshot dos pontos no momento do registo")
    estado = models.CharField(
        max_length=20, choices=Estado.choices, default=Estado.APROVADO,
        help_text="Aprovada automaticamente ao ser registada. Rejeitar/anular faz-se aqui no admin.",
    )

    evidencia_url = models.URLField(blank=True, help_text="Link Strava, foto, etc.")
    evidencia_imagem = models.ImageField(upload_to="gameon/evidencias/%Y/%m/", blank=True, null=True)
    nota_organizacao = models.CharField(max_length=255, blank=True, help_text="Motivo de rejeição, se aplicável")

    data_actividade = models.DateField(default=timezone.now)
    criado_em = models.DateTimeField(auto_now_add=True)
    revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Preenchido automaticamente quando um membro do staff altera o estado no admin.",
    )
    revisado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Actividade"
        verbose_name_plural = "Actividades"
        ordering = ["-criado_em"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(missao__isnull=False, carta_surpresa__isnull=True)
                    | models.Q(missao__isnull=True, carta_surpresa__isnull=False)
                ),
                name="actividade_tem_missao_ou_carta_nao_ambas",
            )
        ]

    def __str__(self):
        origem = self.missao or self.carta_surpresa
        return f"{self.participante} — {origem} ({self.get_estado_display()})"

    def save(self, *args, **kwargs):
        """
        Ponto único de verdade para os efeitos secundários do estado —
        corre sempre, quer a actividade seja criada pelo participante (já
        aprovada automaticamente), quer o estado seja alterado depois no
        admin (ex.: rejeitar por fraude). Assim nunca fica dessincronizado
        entre "como foi criada" e "como foi editada".
        """
        super().save(*args, **kwargs)
        if self.participante_id:
            self.participante.recalcular_pontos_totais()
        if self.carta_surpresa_id:
            CartaAtribuida.objects.filter(
                participante=self.participante, carta=self.carta_surpresa
            ).update(usada=(self.estado == self.Estado.APROVADO))