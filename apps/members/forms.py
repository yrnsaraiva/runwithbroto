from django import forms
from .models import InteresseMembroFundador
import re
from datetime import date


class InteresseMembroFundadorForm(forms.ModelForm):
    """
    Form for registering interest as a 'Membro Fundador'.
    Includes custom validation for phone, email, birth date, and distance.
    """
    class Meta:
        model = InteresseMembroFundador
        fields = '__all__'
        widgets = {
            'nome': forms.TextInput(attrs={
                'placeholder': 'Nome completo',
                'required': True,
            }),
            'telefone': forms.TextInput(attrs={
                'placeholder': '+258 84 000 0000',
                'required': True,
            }),
            'email': forms.EmailInput(attrs={
                'placeholder': 'email@exemplo.com',
                'required': True,
            }),
            'data_nascimento': forms.DateInput(attrs={
                'type': 'date',
                'required': True,
            }),
            'genero': forms.Select(attrs={'required': True}),
            'empresa': forms.TextInput(attrs={'placeholder': 'Empresa'}),
            'cargo': forms.TextInput(attrs={'placeholder': 'Cargo'}),
            'bairro': forms.TextInput(attrs={
                'placeholder': 'Bairro',
                'required': True,
            }),
            'distancia_media': forms.NumberInput(attrs={
                'placeholder': '10',
                'required': True,
                'min': 0,
            }),
            'interesse_principal': forms.Select(attrs={'required': True}),
            'membro_fundador': forms.Select(attrs={'required': True}),
        }

    def clean_telefone(self):
        """Normalize and validate phone number (digits and optional leading +)."""
        telefone = self.cleaned_data.get('telefone')
        if telefone:
            # Remove spaces, parentheses, dashes, dots
            cleaned = re.sub(r'[\s\(\)\-\.]', '', telefone)
            if not cleaned.isdigit() and not (cleaned.startswith('+') and cleaned[1:].isdigit()):
                raise forms.ValidationError(
                    'Número de telefone inválido. Use apenas dígitos e opcionalmente "+" no início.'
                )
            return cleaned
        return telefone

    def clean_email(self):
        """Ensure email is provided (EmailField already validates format)."""
        email = self.cleaned_data.get('email')
        if not email:
            raise forms.ValidationError('Este campo é obrigatório.')
        return email

    def clean_data_nascimento(self):
        """Ensure birth date is in the past and user is at least 16 years old."""
        data = self.cleaned_data.get('data_nascimento')
        if data:
            today = date.today()
            if data >= today:
                raise forms.ValidationError('A data de nascimento deve ser anterior à data atual.')
            # Calculate age
            age = today.year - data.year - (
                (today.month, today.day) < (data.month, data.day)
            )
            if age < 16:
                raise forms.ValidationError('Deves ter pelo menos 16 anos para te inscreveres.')
        return data

    def clean_distancia_media(self):
        """Ensure distance is a non-negative number."""
        dist = self.cleaned_data.get('distancia_media')
        if dist is None:
            raise forms.ValidationError('Este campo é obrigatório.')
        if dist < 0:
            raise forms.ValidationError('A distância média deve ser um valor positivo.')
        return dist