from decimal import Decimal

from django import forms
from django.conf import settings

from communities.models import Community, Need

OTHER = 'otro'


def preset_choices():
    choices = [(str(int(amount)), f'${amount:,.0f}'.replace(',', '.')) for amount in settings.DONATION_PRESET_AMOUNTS]
    return choices + [(OTHER, 'Otro importe')]


class OneTimeDonationForm(forms.Form):
    """Importe de la donación única. Todo se valida aquí, en el servidor."""

    amount_choice = forms.ChoiceField(label='Importe', widget=forms.RadioSelect)
    custom_amount = forms.DecimalField(
        label='Otro importe (ARS)', required=False, max_digits=12, decimal_places=0,
        widget=forms.NumberInput(attrs={'class': 'form-input form-input-lg', 'placeholder': 'Ej: 15000',
                                        'inputmode': 'numeric', 'step': '1'}),
    )
    community = forms.ModelChoiceField(queryset=Community.objects.filter(is_active=True), required=False,
                                       widget=forms.HiddenInput)
    need = forms.ModelChoiceField(queryset=Need.objects.filter(status=Need.Status.ACTIVE,
                                                               community__is_active=True),
                                  required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['amount_choice'].choices = preset_choices()
        self.fields['custom_amount'].widget.attrs.update({
            'min': str(int(settings.DONATION_MIN_AMOUNT)),
            'max': str(int(settings.DONATION_MAX_AMOUNT)),
        })

    def clean(self):
        cleaned = super().clean()
        choice = cleaned.get('amount_choice')
        if choice is None:
            return cleaned
        if choice == OTHER:
            amount = cleaned.get('custom_amount')
            if amount is None:
                self.add_error('custom_amount', 'Ingresá el importe que querés donar.')
                return cleaned
        else:
            # Solo se aceptan los importes sugeridos configurados en el servidor.
            amount = Decimal(choice)
            if amount not in settings.DONATION_PRESET_AMOUNTS:
                self.add_error('amount_choice', 'Importe no válido.')
                return cleaned

        amount = Decimal(amount).quantize(Decimal('1'))
        if amount < settings.DONATION_MIN_AMOUNT:
            self.add_error('custom_amount', f'El importe mínimo es ${settings.DONATION_MIN_AMOUNT:,.0f}.')
        elif amount > settings.DONATION_MAX_AMOUNT:
            self.add_error('custom_amount', f'El importe máximo es ${settings.DONATION_MAX_AMOUNT:,.0f}.')

        need = cleaned.get('need')
        if need and cleaned.get('community') and need.community_id != cleaned['community'].pk:
            raise forms.ValidationError('La necesidad no pertenece a la comunidad seleccionada.')
        if need and amount > need.remaining_amount:
            self.add_error(
                'custom_amount' if choice == OTHER else 'amount_choice',
                f'Para esta necesidad faltan ${need.remaining_amount:,.0f}. Elegí un importe menor '
                'o doná sin seleccionar una necesidad.',
            )
        cleaned['amount'] = amount
        return cleaned


class SubscriptionForm(forms.Form):
    payer_email = forms.EmailField(
        label='Email de tu cuenta de Mercado Pago',
        help_text='Debe ser el mismo email con el que vas a iniciar sesión en Mercado Pago para autorizar el débito.',
        widget=forms.EmailInput(attrs={'class': 'form-input', 'autocomplete': 'email'}),
    )
    accept = forms.BooleanField(
        label='Entiendo que se realizará un débito automático periódico que puedo cancelar cuando quiera.',
    )
