from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import get_template
from datetime import datetime


def send_email(
        subject, template_path_without_extension, datas, 
        to,
        cc = [
            # "sig.anadeb@gmail.com", "cosotogosig@gmail.com", 
            # "palerbo@gmail.com", #Evaluator
            # "gounsougleyename@yahoo.fr", "mass.zato36@gmail.com", #CDDSpecialist
            # "yiroko777@gmail.com", "kegbaof@gmail.com" #Safeguard
        ]):
    
    try:

        if settings.DEBUG:
            to = [settings.RECIPIENT_EMAIL_DEFAULT]
            cc = [settings.RECIPIENT_EMAIL_DEFAULT]
            
        # to = ['adaboubvincent@gmail.com']
        # cc = []
        if type(datas) is dict:
            if 'current_year' not in datas:
                datas['current_year'] = datetime.now().year
            if 'title' not in datas:
                datas['title'] = subject
            if 'see_more_details_label' not in datas:
                datas['see_more_details_label'] = _("See more details")

        plaintext = get_template(template_path_without_extension+'.txt')
        htmly     = get_template(template_path_without_extension+'.html')

        text_content = plaintext.render(datas)
        html_content = htmly.render(datas)
        msg = EmailMultiAlternatives(subject, text_content, to=to, cc=cc)
        msg.attach_alternative(html_content, "text/html")
        msg.send()

        return "success"
    except Exception as e:
        return "error"
    
