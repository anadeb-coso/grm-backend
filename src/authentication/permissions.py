from django.contrib.auth.mixins import UserPassesTestMixin
from django.views.defaults import page_not_found
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied

"""
All Groups permissions
    - SuperAdmin            : 
    - CDD Specialist        : CDDSpecialist
    - Admin                 : Admin
    - Evaluator             : Evaluator
    - Accountant            : Accountant
    - Regional Coordinator  : RegionalCoordinator
    - National Coordinator  : NationalCoordinator
    - General Manager  : GeneralManager
    - Director  : Director
    - Advisor  : Advisor
    - Minister  : Minister
"""

class SpecificPermissionRequiredMixin(UserPassesTestMixin):
    permission_required = None

    def test_func(self):
        user = self.request.user
        if user.groups.filter(name="Viewer").exists() and user.groups.filter(name="Viewer").count() == 1:
            return False
        if not (
                user.groups.all().exists() 
            ):
            return False
        return True
    
    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied
        return super().handle_no_permission()

    def dispatch(self, request, *args, **kwargs):
        return super(SpecificPermissionRequiredMixin, self).dispatch(request, *args, **kwargs)
    

class SuperAdminPermissionRequiredMixin(UserPassesTestMixin):
    permission_required = None

    def test_func(self):
        if self.request.user.is_authenticated and self.request.user.is_superuser:
            return True
        return False
    
    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return page_not_found(self.request, _('Page not found').__str__())
        return super().handle_no_permission()

    def dispatch(self, request, *args, **kwargs):
        return super(SuperAdminPermissionRequiredMixin, self).dispatch(request, *args, **kwargs)


class AdminPermissionRequiredMixin(UserPassesTestMixin):
    permission_required = None

    def test_func(self):
        return True if(self.request.user.is_authenticated and (
            self.request.user.groups.filter(name="Admin").exists()
            or 
            bool(self.request.user.is_superuser)
        )) else False
    
    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return page_not_found(self.request, _('Page not found').__str__())
        return super().handle_no_permission()

    def dispatch(self, request, *args, **kwargs):
        return super(AdminPermissionRequiredMixin, self).dispatch(request, *args, **kwargs)


class CDDSpecialistPermissionRequiredMixin(UserPassesTestMixin):
    permission_required = None

    def test_func(self):
        return True if(self.request.user.is_authenticated and (
            self.request.user.groups.filter(name__in=["CDDSpecialist", "Admin"]).exists()
            or 
            bool(self.request.user.is_superuser)
        )) else False
                
        # if self.request.user.is_authenticated and self.request.user.has_perm('authentication.view_facilitator'):
        #     return True
    
    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return page_not_found(self.request, _('Page not found').__str__())
        return super().handle_no_permission()

    def dispatch(self, request, *args, **kwargs):
        return super(CDDSpecialistPermissionRequiredMixin, self).dispatch(request, *args, **kwargs)


class EvaluatorPermissionRequiredMixin(UserPassesTestMixin):
    permission_required = None

    def test_func(self):
        return True if(self.request.user.is_authenticated and (
            self.request.user.groups.filter(name="Evaluator").exists()
            or 
            self.request.user.groups.filter(name="Admin").exists()
            or 
            bool(self.request.user.is_superuser)
        )) else False
    
    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return page_not_found(self.request, _('Page not found').__str__())
        return super().handle_no_permission()

    def dispatch(self, request, *args, **kwargs):
        return super(EvaluatorPermissionRequiredMixin, self).dispatch(request, *args, **kwargs)


class AccountantPermissionRequiredMixin(UserPassesTestMixin):
    permission_required = None

    def test_func(self):
        return True if(self.request.user.is_authenticated and (
            self.request.user.groups.filter(name="Accountant").exists()
            or 
            self.request.user.groups.filter(name="Admin").exists()
            or 
            bool(self.request.user.is_superuser)
        )) else False
    
    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return page_not_found(self.request, _('Page not found').__str__())
        return super().handle_no_permission()

    def dispatch(self, request, *args, **kwargs):
        return super(AccountantPermissionRequiredMixin, self).dispatch(request, *args, **kwargs)
    

class RegionalCoordinatorPermissionRequiredMixin(UserPassesTestMixin):
    permission_required = None

    def test_func(self):
        return True if(self.request.user.is_authenticated and (
            self.request.user.groups.filter(name="RegionalCoordinator").exists()
            or 
            self.request.user.groups.filter(name="Admin").exists()
            or 
            bool(self.request.user.is_superuser)
        )) else False
    
    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return page_not_found(self.request, _('Page not found').__str__())
        return super().handle_no_permission()

    def dispatch(self, request, *args, **kwargs):
        return super(RegionalCoordinatorPermissionRequiredMixin, self).dispatch(request, *args, **kwargs)


class NationalCoordinatorPermissionRequiredMixin(UserPassesTestMixin):
    permission_required = None

    def test_func(self):
        return True if(self.request.user.is_authenticated and (
            self.request.user.groups.filter(name="NationalCoordinator").exists()
            or 
            self.request.user.groups.filter(name="Admin").exists()
            or 
            bool(self.request.user.is_superuser)
        )) else False
    
    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return page_not_found(self.request, _('Page not found').__str__())
        return super().handle_no_permission()

    def dispatch(self, request, *args, **kwargs):
        return super(NationalCoordinatorPermissionRequiredMixin, self).dispatch(request, *args, **kwargs)



class GeneralManagerPermissionRequiredMixin(UserPassesTestMixin):
    permission_required = None

    def test_func(self):
        return True if(self.request.user.is_authenticated and (
            self.request.user.groups.filter(name="GeneralManager").exists()
            or 
            self.request.user.groups.filter(name="Admin").exists()
            or 
            bool(self.request.user.is_superuser)
        )) else False
    
    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return page_not_found(self.request, _('Page not found').__str__())
        return super().handle_no_permission()

    def dispatch(self, request, *args, **kwargs):
        return super(GeneralManagerPermissionRequiredMixin, self).dispatch(request, *args, **kwargs)


class DirectorPermissionRequiredMixin(UserPassesTestMixin):
    permission_required = None

    def test_func(self):
        return True if(self.request.user.is_authenticated and (
            self.request.user.groups.filter(name="Director").exists()
            or 
            self.request.user.groups.filter(name="Admin").exists()
            or 
            bool(self.request.user.is_superuser)
        )) else False
    
    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return page_not_found(self.request, _('Page not found').__str__())
        return super().handle_no_permission()

    def dispatch(self, request, *args, **kwargs):
        return super(DirectorPermissionRequiredMixin, self).dispatch(request, *args, **kwargs)
    

class AdvisorPermissionRequiredMixin(UserPassesTestMixin):
    permission_required = None

    def test_func(self):
        return True if(self.request.user.is_authenticated and (
            self.request.user.groups.filter(name="Advisor").exists()
            or 
            self.request.user.groups.filter(name="Admin").exists()
            or 
            bool(self.request.user.is_superuser)
        )) else False
    
    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return page_not_found(self.request, _('Page not found').__str__())
        return super().handle_no_permission()

    def dispatch(self, request, *args, **kwargs):
        return super(AdvisorPermissionRequiredMixin, self).dispatch(request, *args, **kwargs)
    


class MinisterPermissionRequiredMixin(UserPassesTestMixin):
    permission_required = None

    def test_func(self):
        return True if(self.request.user.is_authenticated and (
            self.request.user.groups.filter(name="Minister").exists()
            or 
            self.request.user.groups.filter(name="Admin").exists()
            or 
            bool(self.request.user.is_superuser)
        )) else False
    
    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return page_not_found(self.request, _('Page not found').__str__())
        return super().handle_no_permission()

    def dispatch(self, request, *args, **kwargs):
        return super(MinisterPermissionRequiredMixin, self).dispatch(request, *args, **kwargs)
    


class SafeguardPermissionRequiredMixin(UserPassesTestMixin):
    permission_required = None

    def test_func(self):
        return True if(self.request.user.is_authenticated and (
            self.request.user.groups.filter(name="Safeguard").exists()
            or 
            self.request.user.groups.filter(name="Admin").exists()
            or 
            bool(self.request.user.is_superuser)
        )) else False
    
    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return page_not_found(self.request, _('Page not found').__str__())
        return super().handle_no_permission()

    def dispatch(self, request, *args, **kwargs):
        return super(SafeguardPermissionRequiredMixin, self).dispatch(request, *args, **kwargs)