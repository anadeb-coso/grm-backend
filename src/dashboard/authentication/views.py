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
from dashboard.authentication.forms import RegisterADLForm, ConfirmCodeForm


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
    success_url = reverse_lazy('dashboard:diagnostics:home')
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

