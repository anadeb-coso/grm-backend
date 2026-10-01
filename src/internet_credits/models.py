import re

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from grm.models_base import TimestampedSyncModel, safe_json_value

# ---------------------------------------------------------------------------
# Traçabilité du forfait internet mensuel (3 Go / 3 000 FCFA / 30 jours) envoyé à chaque
# membre CVGP. Un CVGP = un CVD (un ou plusieurs villages) : une seule confirmation CVGP par
# CVD et par mois, doublée d'une confirmation du FC/AC qui couvre ce CVD.
#
# Les trois modèles héritent de `TimestampedSyncModel` (UUID, `updated_at`, tombstone
# `is_deleted`) : ils sont synchronisés avec le mobile MGP (WatermelonDB, cf. sync/views.py) —
# campagnes et bénéficiaires en lecture seule, confirmations en écriture.
# ---------------------------------------------------------------------------

CVGP_GROUP = 'CVGPMembers'
# FC/AC : même groupe que la colonne "AC" des localités pilotes (dashboard/templates/grm/issue_list.html).
FC_GROUPS = ('CommunityFacilitator',)
# Groupe optionnel donnant accès à l'espace web, en plus de `Admin` et des superusers.
MANAGER_GROUP = 'InternetCreditManager'

FRENCH_MONTHS = (
    'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
    'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre',
)

DEFAULT_CVGP_MESSAGE = (
    "CVGP du CVD {cvd} a bien reçu le crédit internet pour le mois de {mois} {annee}, "
    "et j'en confirme sa réception"
)
DEFAULT_FC_MESSAGE = DEFAULT_CVGP_MESSAGE
DEFAULT_ATTESTATION_TEXT = (
    "Je confirme que ces CVD ont bien reçu le forfait internet ({forfait}) pour le mois de "
    "{mois} {annee}."
)
DEFAULT_AGREEMENT_TEXT = (
    "Je confirme que le CVGP du CVD {cvd} a bien reçu le forfait internet ({forfait}) pour le "
    "mois de {mois} {annee}."
)
DEFAULT_PACKAGE_LABEL = '3 Go valables 30 jours'
DEFAULT_AMOUNT = 3000


def render_message(template, context):
    """Remplace les champs `{cle}` connus de `context` dans `template`. Un simple `replace` plutôt
    que `str.format` : le texte est saisi librement sur le web et peut contenir d'autres
    accolades ou des champs inconnus, qui doivent rester tels quels au lieu de lever une erreur."""
    text = template or ''
    for key, value in context.items():
        text = text.replace('{' + key + '}', '' if value is None else str(value))
    return text


class InternetCreditCampaign(TimestampedSyncModel):
    period = models.DateField(verbose_name=_('month'), help_text=_('Any day of the month; stored as the 1st.'))
    sent_date = models.DateField(verbose_name=_('package sending date'))
    package_label = models.CharField(max_length=100, default=DEFAULT_PACKAGE_LABEL, verbose_name=_('package'))
    amount = models.PositiveIntegerField(default=DEFAULT_AMOUNT, verbose_name=_('amount (FCFA)'))
    cvgp_message_template = models.TextField(default=DEFAULT_CVGP_MESSAGE, verbose_name=_('CVGP checkbox message'))
    fc_message_template = models.TextField(default=DEFAULT_FC_MESSAGE, verbose_name=_('FC/AC checkbox message'))
    attestation_text = models.TextField(default=DEFAULT_ATTESTATION_TEXT, verbose_name=_('monthly PDF attestation'))
    agreement_text = models.TextField(default=DEFAULT_AGREEMENT_TEXT, verbose_name=_('CVD PDF agreement message'))
    signatory_name = models.CharField(max_length=255, blank=True, default='', verbose_name=_('signatory name'))
    signatory_title = models.CharField(max_length=255, blank=True, default='', verbose_name=_('signatory title'))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name=_('created by'),
    )

    class Meta:
        ordering = ['-period']
        verbose_name = _('internet credit campaign')
        verbose_name_plural = _('internet credit campaigns')
        constraints = [
            models.UniqueConstraint(
                fields=['period'], condition=Q(is_deleted=False), name='unique_active_internet_credit_period',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.period:
            self.period = self.period.replace(day=1)
        super().save(*args, **kwargs)

    @property
    def month_name(self):
        return FRENCH_MONTHS[self.period.month - 1]

    @property
    def month_label(self):
        return f'{self.month_name} {self.period.year}'

    @property
    def amount_display(self):
        return f'{self.amount:,}'.replace(',', ' ') + ' FCFA'

    def message_context(self, **extra):
        context = {
            'mois': self.month_name,
            'annee': self.period.year,
            'forfait': self.package_label,
            'montant': self.amount,
            'date_envoi': self.sent_date.strftime('%d/%m/%Y') if self.sent_date else '',
        }
        context.update(extra)
        return context

    def __str__(self):
        return self.month_label


class InternetCreditBeneficiary(TimestampedSyncModel):
    """Une ligne par membre CVGP (= un CVD) et par campagne, générée par
    `internet_credits.services.sync_campaign_beneficiaries`. Nom, téléphone, CVD et villages sont
    figés au moment de la génération : l'historique d'un mois ne doit pas changer si le membre
    change plus tard de téléphone ou de CVD."""
    campaign = models.ForeignKey(InternetCreditCampaign, on_delete=models.CASCADE, related_name='beneficiaries')
    cvgp_member = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='internet_credit_beneficiaries', verbose_name=_('CVGP member'),
    )
    member_name = models.CharField(max_length=255, blank=True, default='')
    phone_number = models.CharField(max_length=45, blank=True, default='')
    # Référence à administrativelevels.CVD (base `mis`) : simple identifiant, jamais de FK
    # cross-db (même principe que Issue.administrative_region, CLAUDE.md §2.1).
    cvd_id = models.IntegerField(null=True, blank=True, db_index=True)
    cvd_name = models.CharField(max_length=255, blank=True, default='')
    # Ids (chaînes, comme `Adl.administrative_region_ids`) et noms des villages du CVD : servent
    # à déterminer quels FC/AC peuvent confirmer (sync/views.py + services.fc_village_ids).
    village_ids = models.JSONField(default=list, blank=True)
    village_names = models.TextField(blank=True, default='')
    cvgp_message = models.TextField(blank=True, default='')
    fc_message = models.TextField(blank=True, default='')
    # Anomalie de rattachement au CVD (aucun ou plusieurs CVD trouvés dans `mis`), affichée sur le web.
    resolution_warning = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['cvd_name', 'member_name']
        verbose_name = _('internet credit beneficiary')
        verbose_name_plural = _('internet credit beneficiaries')
        constraints = [
            models.UniqueConstraint(
                fields=['campaign', 'cvgp_member'], condition=Q(is_deleted=False),
                name='unique_active_internet_credit_beneficiary',
            ),
        ]

    @property
    def village_ids_value(self):
        return [str(v) for v in (safe_json_value(self.village_ids) or [])]

    @property
    def label(self):
        return self.cvd_name or self.village_names or self.member_name

    @property
    def show_village_names(self):
        """Faux quand le nom du CVD n'est que la liste de ses villages (CVD sans nom dans `mis`,
        cf. CVD.get_name) : inutile de répéter la liste sous le nom."""
        label_parts = {p.strip().upper() for p in re.split(r'[/,]', self.label or '') if p.strip()}
        village_parts = {p.strip().upper() for p in (self.village_names or '').split(',') if p.strip()}
        return bool(village_parts) and village_parts != label_parts

    def __str__(self):
        return f'{self.campaign} — {self.label}'


class InternetCreditConfirmation(TimestampedSyncModel):
    ROLE_CVGP = 'cvgp'
    ROLE_FC = 'fc'
    ROLE_CHOICES = [(ROLE_CVGP, _('CVGP member')), (ROLE_FC, _('FC/AC'))]

    SOURCE_GRM_MOBILE = 'grm_mobile'
    SOURCE_CDD_MOBILE = 'cdd_mobile'
    SOURCE_CHOICES = [(SOURCE_GRM_MOBILE, _('MGP mobile')), (SOURCE_CDD_MOBILE, _('DCC mobile'))]

    beneficiary = models.ForeignKey(InternetCreditBeneficiary, on_delete=models.CASCADE, related_name='confirmations')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='internet_credit_confirmations',
    )
    confirmed_by_name = models.CharField(max_length=255, blank=True, default='')
    # Texte exact coché par la personne, figé : une modification ultérieure du message de la
    # campagne ne doit pas changer ce qui a été attesté.
    message = models.TextField()
    checked = models.BooleanField(default=False)
    # Image PNG/JPEG en data URL base64 (`data:image/png;base64,...`), dessinée sur le mobile.
    signature = models.TextField()
    description = models.TextField(blank=True, null=True)
    confirmed_at = models.DateTimeField()
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_GRM_MOBILE)

    class Meta:
        ordering = ['confirmed_at']
        verbose_name = _('internet credit confirmation')
        verbose_name_plural = _('internet credit confirmations')
        constraints = [
            models.UniqueConstraint(
                fields=['beneficiary', 'role', 'confirmed_by'], condition=Q(is_deleted=False),
                name='unique_active_internet_credit_confirmation',
            ),
        ]

    def __str__(self):
        return f'{self.beneficiary} — {self.get_role_display()} — {self.confirmed_by_name}'
