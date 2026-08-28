from django import forms

from .models import Actividade, CartaSurpresa, Missao


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
            "data_actividade": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["missao"].queryset = Missao.objects.filter(activa=True)
        self.fields["missao"].required = False
        self.fields["carta_surpresa"].queryset = CartaSurpresa.objects.filter(activa=True)
        self.fields["carta_surpresa"].required = False

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

    def save(self, participante, commit=True):
        actividade = super().save(commit=False)
        actividade.participante = participante
        origem = actividade.missao or actividade.carta_surpresa
        actividade.pontos = origem.pontos  # snapshot no momento do registo
        if commit:
            actividade.save()
        return actividade