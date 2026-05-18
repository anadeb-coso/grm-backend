from django.http import HttpResponseRedirect, HttpResponse
from django.conf import settings
from django.utils.translation import get_language
from django.contrib.auth.decorators import login_required
import requests
from django.http import Http404

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





@login_required
def profile(request):
    if request.method == 'POST':
        try:
            scheme = request.scheme
            domain = request.get_host()
            full_url = f"{scheme}://{domain}"
            language = get_language()

            previous_url = request.headers.get('Referer', full_url)

            #Recuperation de Token
            session = requests.Session()
            response = session.get(f"{settings.CDD_URL_BASE}/authentication/get-csrf-token/")

            if response.status_code == 200:
                data = response.json()
                token = data.get("csrfToken")
            else:
                raise Http404
            
            cookies = session.cookies.get_dict()
            headers = {
                "X-CSRFToken": token,
                "Referer": f"{settings.CDD_URL_BASE}/",
                "Origin": settings.CDD_URL_BASE
            }
            post_data = {
                'email': request.user.email,
                'code': get_validation_code(request.user.email),
                'redirection_url': full_url,
                'csrfmiddlewaretoken': token,
                'language': language,
                'previous_url': previous_url,
            }
            
            response_post = session.post(f"{settings.CDD_URL_BASE}/{language}/user-manager/", headers=headers, cookies=cookies, data=post_data)

            content = response_post.text\
                .replace('/static/', f'{settings.CDD_URL_BASE}/static/')\
                .replace(f'url: "/{language}/', f'url: "{settings.CDD_URL_BASE}/{language}/')\
                .replace('action="/i18n/', f'action="{settings.CDD_URL_BASE}/i18n/')


            return HttpResponse(content)


        except Exception as e:
            print("Erreur :", e)
            raise Http404
        
    raise Http404