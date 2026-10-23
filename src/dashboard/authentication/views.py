from django.shortcuts import render
from rest_framework import status
from django.views.generic import FormView
from django.urls import reverse_lazy
from django.contrib.auth import (
	authenticate, 
	login as loginAction
)

from authentication.models import User
from dashboard.mixins import PageMixin
from dashboard.authentication.forms import RegisterADLForm, ConfirmCodeForm, FirstLoginPasswordForm
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.utils.translation import get_language, gettext_lazy
from authentication.password_change import CHECKED_SESSION_KEY, change_initial_password_on_cdd, password_change_required


def handler400(request, exception):
    return render(
        request,
        template_name='common/400.html',
        status=status.HTTP_400_BAD_REQUEST,
        content_type='text/html'
    )


def handler403(request, exception):
    return render(
        request,
        template_name='common/403.html',
        status=status.HTTP_403_FORBIDDEN,
        content_type='text/html'
    )


def handler404(request, exception):
    return render(
        request,
        template_name='common/404.html',
        status=status.HTTP_404_NOT_FOUND,
        content_type='text/html'
    )


def handler500(request):
    return render(
        request,
        template_name='common/500.html',
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content_type='text/html'
    )



class RegisterADLView(PageMixin, FormView):
    template_name = 'authentication/register.html'
    form_class = RegisterADLForm
    success_url = None
    def form_valid(self, form):
        data = form.cleaned_data
        self.success_url = reverse_lazy('dashboard:authentication:confirm_code', args=[self.request.POST.get("csrfmiddlewaretoken"),data['email'], data['password']])
        return super().form_valid(form)

class ConfirmCodeADLView(PageMixin, FormView):
    template_name = 'authentication/confirm_code.html'
    form_class = ConfirmCodeForm
    success_url = reverse_lazy('dashboard:grm:review_issues')
    password = None
    email = None

    def dispatch(self, request, csrf_token, email, password ,*args, **kwargs):
        self.password = password
        self.email = email
        return super().dispatch(request, *args, **kwargs)
    
    def get_form_kwargs(self):
        self.initial = {'email': self.email, 'password': self.password}
        return super().get_form_kwargs()
    
    def form_valid(self, form):
        data = form.cleaned_data
        user = User.objects.filter(email__iexact=self.email).first()
        user = authenticate(self.request, username=user.username, password=self.password)
        if user is not None:
            loginAction(self.request, user)

        return super().form_valid(form)


class FirstLoginPasswordView(LoginRequiredMixin, FormView):
	"""Changement obligatoire du mot de passe initial d'un compte créé dans le DCC (PasswordChangeRequiredMiddleware
	y renvoie les pages du dashboard tant qu'il n'est pas fait). Le DCC l'applique à toutes les plateformes, ce
	compte compris ; la session courante reste ouverte."""
	template_name = 'authentication/first_login_password.html'
	form_class = FirstLoginPasswordForm

	def dispatch(self, request, *args, **kwargs):
		if request.user.is_authenticated and not password_change_required(request.user.email):
			request.session[CHECKED_SESSION_KEY] = True
			return redirect(settings.LOGIN_REDIRECT_URL)
		return super().dispatch(request, *args, **kwargs)

	def form_valid(self, form):
		data = form.cleaned_data
		ok, message = change_initial_password_on_cdd(
			self.request.user.email, data['current_password'], data['new_password'], data['new_password_confirm'],
			'mgp_web', language=get_language(),
		)
		if not ok:
			form.add_error(None, message)
			return self.form_invalid(form)
		# Le DCC vient de reporter le nouveau mot de passe sur ce compte : la session courante est gardée.
		update_session_auth_hash(self.request, User.objects.get(pk=self.request.user.pk))
		self.request.session[CHECKED_SESSION_KEY] = True
		messages.success(self.request, gettext_lazy("Your password has been changed. It is now valid on all the platforms (DCC, MGP and SIG)."))
		return redirect(settings.LOGIN_REDIRECT_URL)
