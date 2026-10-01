from rest_framework import serializers

from . import services
from .models import InternetCreditBeneficiary, InternetCreditCampaign, InternetCreditConfirmation

# ---------------------------------------------------------------------------
# Pull WatermelonDB (mobile MGP) — colonnes attendues par grm-frontend/src/database/schema.js.
# ---------------------------------------------------------------------------


class InternetCreditCampaignSyncSerializer(serializers.ModelSerializer):
    month_label = serializers.ReadOnlyField()

    class Meta:
        model = InternetCreditCampaign
        fields = [
            'id', 'period', 'month_label', 'sent_date', 'package_label', 'amount',
            'is_deleted', 'created_at', 'updated_at',
        ]


class InternetCreditBeneficiarySyncSerializer(serializers.ModelSerializer):
    class Meta:
        model = InternetCreditBeneficiary
        fields = [
            'id', 'campaign', 'cvgp_member', 'member_name', 'phone_number', 'cvd_id', 'cvd_name',
            'village_names', 'cvgp_message', 'fc_message', 'is_deleted', 'created_at', 'updated_at',
        ]


class InternetCreditConfirmationSyncSerializer(serializers.ModelSerializer):
    """`signature` n'est volontairement pas renvoyée au pull : le mobile n'a jamais besoin
    d'afficher la signature d'un autre (seulement l'état « confirmé »), et un FC couvrant une
    vingtaine de CVD téléchargerait sinon chaque mois plusieurs Mo d'images. `has_signature` suffit."""
    has_signature = serializers.SerializerMethodField()

    class Meta:
        model = InternetCreditConfirmation
        fields = [
            'id', 'beneficiary', 'role', 'confirmed_by', 'confirmed_by_name', 'message', 'checked',
            'has_signature', 'description', 'confirmed_at', 'source', 'is_deleted', 'created_at',
            'updated_at',
        ]

    def get_has_signature(self, obj):
        return bool(obj.signature)


# ---------------------------------------------------------------------------
# API REST (mobile DCC)
# ---------------------------------------------------------------------------


def _confirmation_summary(confirmation):
    if confirmation is None:
        return None
    return {
        'id': str(confirmation.id),
        'confirmed_by_name': confirmation.confirmed_by_name,
        'confirmed_at': confirmation.confirmed_at.isoformat(),
    }


def notification_payload(user, beneficiary):
    campaign = beneficiary.campaign
    role = services.role_for(user, beneficiary)
    cvgp = services.cvgp_confirmation(beneficiary)
    fcs = services.fc_confirmations(beneficiary)
    mine = next((c for c in services.get_active_confirmations(beneficiary)
                 if c.role == role and c.confirmed_by_id == user.id), None)
    return {
        'id': str(beneficiary.id),
        'role': role,
        'message': beneficiary.cvgp_message if role == InternetCreditConfirmation.ROLE_CVGP else beneficiary.fc_message,
        'campaign': {
            'id': str(campaign.id),
            'period': campaign.period.isoformat(),
            'month_label': campaign.month_label,
            'sent_date': campaign.sent_date.isoformat() if campaign.sent_date else None,
            'package_label': campaign.package_label,
            'amount': campaign.amount,
        },
        'cvd_name': beneficiary.label,
        'village_names': beneficiary.village_names,
        'member_name': beneficiary.member_name,
        'phone_number': beneficiary.phone_number,
        'my_confirmation': _confirmation_summary(mine),
        'cvgp_confirmation': _confirmation_summary(cvgp),
        'fc_confirmations': [_confirmation_summary(c) for c in fcs],
    }


class ConfirmationCreateSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    beneficiary = serializers.UUIDField()
    checked = serializers.BooleanField()
    signature = serializers.CharField(trim_whitespace=False)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    message = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    confirmed_at = serializers.CharField(required=False, allow_blank=True, allow_null=True)
