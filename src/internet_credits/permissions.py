from django.contrib.auth.mixins import UserPassesTestMixin
from django.utils.translation import gettext_lazy as _
from django.views.defaults import page_not_found

from .models import MANAGER_GROUP


def can_manage_internet_credits(user):
    """Superuser, groupe `Admin`, ou groupe dédié `InternetCreditManager` (créé vide par la
    migration 0002, à peupler depuis l'admin Django si besoin)."""
    return bool(
        user.is_authenticated
        and (user.is_superuser or user.groups.filter(name__in=['Admin', MANAGER_GROUP]).exists())
    )


class InternetCreditManagerRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return can_manage_internet_credits(self.request.user)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return page_not_found(self.request, _('Page not found').__str__())
        return super().handle_no_permission()
