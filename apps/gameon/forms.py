import re

from django import forms

from .models import Actividade, CartaSurpresa, Missao


def normalizar_telefone(telefone: str) -> str:
    """
    Normaliza um número moçambicano para um formato consistente (+258XXXXXXXXX),
    para que o mesmo participante seja sempre encontrado pelo mesmo número,
    independentemente de como o escreveu (com espaços, com/sem +258, com 0 inicial).
    """
    digitos = re.sub(r"\D", "", telefone or "")
    digitos = digitos.lstrip("0")
    if digitos.startswith("258"):
        return f"+{digitos}"
    return f"+258{digitos}"


class ParticipanteIdentificacaoForm(forms.Form):
    """
    Identificação leve por número de telefone — sem password, sem conta.
    Se o número já existir, entra nesse participante; caso contrário, cria um novo.
    """

    telefone = forms.CharField(
        label="Número de telefone",
        widget=forms.TextInput(attrs={"placeholder": "84 472 3840", "inputmode": "tel", "class": "field"}),
    )
    nome = forms.CharField(
        label="Nome",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "O teu nome", "class": "field"}),
    )

    def clean_telefone(self):
        return normalizar_telefone(self.cleaned_data["telefone"])


class ActividadeForm(forms.ModelForm):
    """
    Formulário que o participante usa para registar que cumpriu um desafio.
    Aceita missão do catálogo OU carta surpresa activa, nunca ambas — a
    validação espelha o CheckConstraint do modelo para dar erro amigável
    antes de tentar gravar na base de dados.
    """

    class Meta:
        model = Actividade
        fields = ["missao", "carta_surpresa", "evidencia_url", "evidencia_imagem", "data_actividade"]
        widgets = {
            "data_actividade": forms.DateInput(attrs={"type": "date", "class": "field"}),
            "evidencia_url": forms.URLInput(attrs={"class": "field"}),
            "evidencia_imagem": forms.ClearableFileInput(attrs={"class": "field"}),
        }

    def __init__(self, *args, participante=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.participante = participante

        self.fields["missao"].queryset = Missao.objects.filter(activa=True)
        self.fields["missao"].required = False
        self.fields["missao"].widget.attrs["class"] = "field"

        if participante is not None:
            cartas_disponiveis = CartaSurpresa.objects.filter(
                atribuicoes__participante=participante, atribuicoes__usada=False, activa=True
            ).distinct()
        else:
            cartas_disponiveis = CartaSurpresa.objects.none()

        self.fields["carta_surpresa"].queryset = cartas_disponiveis
        self.fields["carta_surpresa"].required = False
        self.fields["carta_surpresa"].widget.attrs["class"] = "field"
        self.fields["carta_surpresa"].empty_label = (
            "— nenhuma carta atribuída de momento —" if not cartas_disponiveis.exists() else "— escolhe uma —"
        )

    def clean(self):
        cleaned = super().clean()
        missao = cleaned.get("missao")
        carta = cleaned.get("carta_surpresa")

        if not missao and not carta:
            raise forms.ValidationError("Escolhe uma missão do catálogo ou uma carta surpresa activa.")
        if missao and carta:
            raise forms.ValidationError("Escolhe apenas uma: missão OU carta surpresa, não as duas.")

        if not cleaned.get("evidencia_url") and not cleaned.get("evidencia_imagem"):
            raise forms.ValidationError("Junta uma evidência: link (ex.: Strava) ou uma foto.")

        return cleaned

    def save(self, participante, edicao, commit=True):
        actividade = super().save(commit=False)
        actividade.participante = participante
        actividade.edicao = edicao
        actividade.estado = Actividade.Estado.APROVADO
        origem = actividade.missao or actividade.carta_surpresa
        actividade.pontos = origem.pontos  # snapshot no momento do registo
        if commit:
            actividade.save()  # dispara recálculo de pontos e libertação/uso da carta
        return actividade