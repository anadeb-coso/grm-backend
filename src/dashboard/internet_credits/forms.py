from django import forms
from django.utils.translation import gettext_lazy as _

from internet_credits import services
from internet_credits.models import InternetCreditCampaign

PLACEHOLDERS_HELP = _(
    'Available fields: {cvd}, {villages}, {mois}, {annee}, {forfait}, {montant}, {date_envoi}, {nom}, {telephone}'
)


def _textarea(rows=3):
    return forms.Textarea(attrs={'rows': rows, 'class': 'form-control'})


class CampaignForm(forms.ModelForm):
    period = forms.DateField(
        label=_('Month'), input_formats=['%Y-%m', '%Y-%m-%d'],
        widget=forms.DateInput(attrs={'type': 'month', 'class': 'form-control'}, format='%Y-%m'),
    )
    sent_date = forms.DateField(
        label=_('Package sending date'), input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
    )

    class Meta:
        model = InternetCreditCampaign
        fields = [
            'period', 'sent_date', 'package_label', 'amount',
            'cvgp_message_template', 'fc_message_template',
            'attestation_text', 'agreement_text', 'signatory_name', 'signatory_title',
        ]
        labels = {
            'package_label': _('Package'),
            'amount': _('Amount (FCFA)'),
            'cvgp_message_template': _('Checkbox message for the CVGP member'),
            'fc_message_template': _('Checkbox message for the FC/AC'),
            'attestation_text': _('Attestation at the bottom of the monthly PDF'),
            'agreement_text': _('Agreement message of the CVD PDF'),
            'signatory_name': _('Signatory name (PDF)'),
            'signatory_title': _('Signatory title (PDF)'),
        }
        help_texts = {
            'cvgp_message_template': PLACEHOLDERS_HELP,
            'fc_message_template': PLACEHOLDERS_HELP,
            'attestation_text': PLACEHOLDERS_HELP,
            'agreement_text': PLACEHOLDERS_HELP,
        }
        widgets = {
            'package_label': forms.TextInput(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'cvgp_message_template': _textarea(),
            'fc_message_template': _textarea(),
            'attestation_text': _textarea(),
            'agreement_text': _textarea(),
            'signatory_name': forms.TextInput(attrs={'class': 'form-control'}),
            'signatory_title': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean_period(self):
        period = self.cleaned_data['period'].replace(day=1)
        duplicates = InternetCreditCampaign.objects.filter(period=period, is_deleted=False)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError(_('A package is already registered for this month.'))
        return period


class ExportOptionsForm(forms.Form):
    """Options d'un export PDF (mensuel ou par CVD) : texte d'attestation/d'accord personnalisé,
    signataire, et signature (cadre vide à signer à la main, ou signature dessinée à l'écran)."""
    SIGNATURE_BLANK = 'blank'
    SIGNATURE_DRAWN = 'drawn'
    SIGNATURE_MODES = [
        (SIGNATURE_BLANK, _('Empty frame (handwritten signature after printing)')),
        (SIGNATURE_DRAWN, _('Sign on screen')),
    ]

    text = forms.CharField(label=_('Text'), required=False, widget=_textarea(3), help_text=PLACEHOLDERS_HELP)
    place = forms.CharField(label=_('Done at'), required=False, max_length=100,
                            widget=forms.TextInput(attrs={'class': 'form-control'}))
    signatory_name = forms.CharField(label=_('Signatory name'), required=False, max_length=255,
                                     widget=forms.TextInput(attrs={'class': 'form-control'}))
    signatory_title = forms.CharField(label=_('Signatory title'), required=False, max_length=255,
                                      widget=forms.TextInput(attrs={'class': 'form-control'}))
    signature_mode = forms.ChoiceField(label=_('Signature'), choices=SIGNATURE_MODES, initial=SIGNATURE_BLANK,
                                       widget=forms.RadioSelect(attrs={'class': 'form-check-input ic-signature-mode'}))
    drawn_signature = forms.CharField(required=False, widget=forms.HiddenInput(attrs={'class': 'ic-drawn-signature'}))
    remember = forms.BooleanField(label=_('Keep this text and signatory for this month'), required=False,
                                  widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('signature_mode') == self.SIGNATURE_DRAWN:
            try:
                services.validate_signature(cleaned.get('drawn_signature'))
            except services.ConfirmationRejected:
                self.add_error('drawn_signature', _('Please draw the signature before exporting.'))
        return cleaned
