from django.contrib import admin

from .models import InternetCreditBeneficiary, InternetCreditCampaign, InternetCreditConfirmation


@admin.register(InternetCreditCampaign)
class InternetCreditCampaignAdmin(admin.ModelAdmin):
    list_display = ('period', 'sent_date', 'package_label', 'amount', 'is_deleted', 'updated_at')
    list_filter = ('is_deleted',)


@admin.register(InternetCreditBeneficiary)
class InternetCreditBeneficiaryAdmin(admin.ModelAdmin):
    list_display = ('campaign', 'cvd_name', 'member_name', 'phone_number', 'is_deleted')
    list_filter = ('campaign', 'is_deleted')
    search_fields = ('cvd_name', 'member_name', 'phone_number', 'village_names')


@admin.register(InternetCreditConfirmation)
class InternetCreditConfirmationAdmin(admin.ModelAdmin):
    list_display = ('beneficiary', 'role', 'confirmed_by_name', 'confirmed_at', 'source', 'is_deleted')
    list_filter = ('role', 'source', 'is_deleted')
    exclude = ('signature',)
