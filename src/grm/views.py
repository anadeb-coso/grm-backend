from django.http import HttpResponseRedirect, HttpResponse
from django.conf import settings
from django.utils.translation import get_language
from django.contrib.auth.decorators import login_required
import requests
from django.http import Http404
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from grm.functions import get_validation_code

def set_language(request):
    response = HttpResponseRedirect('/')
    if request.method == 'POST':
        try:
            language = request.POST.get('language')
            next = request.POST.get('next')
            next_url_generate = False
            language_code = get_language()
            
            if next and language_code and next.startswith("/"+language_code+"/") :
                next = next[(len(language_code)+2):]
                next_url_generate = True
                
            if language:
                if language != settings.LANGUAGE_CODE and [lang for lang in settings.LANGUAGES if lang[0] == language]:
                    redirect_path = f'/{language}/{next}' if next_url_generate else f'/{language}/'
                elif language == settings.LANGUAGE_CODE:
                    redirect_path = f'/{next}' if next_url_generate else '/'
                else:
                    return response
                from django.utils import translation
                translation.activate(language)
                response = HttpResponseRedirect(redirect_path)
                response.set_cookie(settings.LANGUAGE_COOKIE_NAME, language)
        except Exception as exc:
            pass
    return response





def _profile_language(request):
    """`/profile/` is not prefixed by the language: the sidebar sends the page's one, kept for the password step."""
    from django.utils import translation

    language = request.GET.get('language') or request.POST.get('language') or request.session.get('profile_language')
    if language in dict(settings.LANGUAGES):
        request.session['profile_language'] = language
        translation.activate(language)
    return get_language()


@login_required
def profile(request):
    """Profile page of the logged-in user, served by the MGP itself (same content as the DCC one). Opened with a
    GET; a POST (old link) is redirected to the GET page."""
    from django.shortcuts import redirect

    from authentication.profile_service import build_profile_details
    from dashboard.authentication.forms import FirstLoginPasswordForm

    language = _profile_language(request)
    if request.method == 'POST':
        return redirect(f"{request.path}?language={language}")
    return render(request, 'profile.html', {
        'title': _('Profile'),
        'd': build_profile_details(request.user, language),
        'password_form': FirstLoginPasswordForm(),
        'open_password': request.GET.get('password') == '1',
    })


@login_required
def profile_change_password(request):
    """New password for all the person's accounts (DCC, SIG, facilitator, MGP), applied by the DCC."""
    from django.contrib import messages
    from django.contrib.auth import get_user_model, update_session_auth_hash
    from django.shortcuts import redirect

    from authentication.password_change import CHECKED_SESSION_KEY
    from authentication.profile_service import build_profile_details, change_password_on_all_platforms
    from dashboard.authentication.forms import FirstLoginPasswordForm

    if request.method != 'POST':
        return redirect('profile')
    _profile_language(request)
    form = FirstLoginPasswordForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        ok, message = change_password_on_all_platforms(
            request.user.email, data['current_password'], data['new_password'], data['new_password_confirm'],
            language=get_language(),
        )
        if ok:
            # The DCC has just written the new password on this MGP account: keep this session open.
            update_session_auth_hash(request, get_user_model().objects.get(pk=request.user.pk))
            request.session[CHECKED_SESSION_KEY] = True
            messages.success(request, message or _("The password has been changed on all the platforms."))
            return redirect('profile')
        form.add_error(None, message)
    return render(request, 'profile.html', {
        'title': _('Profile'),
        'd': build_profile_details(request.user, _profile_language(request)),
        'password_form': form,
        'open_password': True,
    })
