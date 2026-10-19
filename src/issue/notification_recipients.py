"""Destinataires des notifications email des issues (listes de l'équipe MGP), gérés dans l'admin
Django (`issue.models.NotificationRecipient`) au lieu des listes autrefois codées en dur dans
grm/constants.py."""
import sys

from issue.models import NotificationRecipient

R = NotificationRecipient
ALL_GROUPS = tuple(code for code, _label in R.GROUP_CHOICES)

# Contenu des anciennes listes de grm/constants.py au moment de leur passage en base : les adresses
# qui y étaient mises en commentaire sont reprises inactives (réactivables dans l'admin).
# (liste, adresse, rôle, active)
LEGACY_RECIPIENTS = (
    (R.GROUP_SAFEGUARD_SPECIALISTS, 'yiroko777@gmail.com', '', False),
    (R.GROUP_SAFEGUARD_SPECIALISTS, 'kegbaof@gmail.com', '', True),
    (R.GROUP_SAFEGUARD_SPECIALISTS, 'adaboubvincent@gmail.com', '', False),
    (R.GROUP_SAFEGUARD_SPECIALISTS, 'gtchilingatolbert@yahoo.fr', '', True),
    (R.GROUP_SAFEGUARD_ASSISTANTS, 'badassan13@gmail.com', '', False),
    (R.GROUP_SAFEGUARD_ASSISTANTS, 'ourorachid2013@gmail.com', '', True),
    (R.GROUP_SAFEGUARD_ASSISTANTS, 'estherdjallo@gmail.com', '', False),
    (R.GROUP_SAFEGUARD_ASSISTANTS, 'aholouvitt@gmail.com', '', True),
    (R.GROUP_COORDINATORS, 'dametouglet@hotmail.com', '', True),
    (R.GROUP_COORDINATORS, 'tdametougle@gmail.com', '', True),
    (R.GROUP_REGIONAL_COORDINATORS, 'nikabouolivier2017@gmail.com', '', True),
    (R.GROUP_REGIONAL_COORDINATORS, 'ayassouhola@gmail.com', '', True),
    (R.GROUP_REGIONAL_COORDINATORS, 'moukeram@yahoo.fr', '', False),
    (R.GROUP_OTHER_SPECIALISTS, 'palerbo@gmail.com', 'Evaluator', True),
    (R.GROUP_OTHER_SPECIALISTS, 'gounsougleyename@yahoo.fr', 'CDDSpecialist', True),
    (R.GROUP_OTHER_SPECIALISTS, 'mass.zato36@gmail.com', 'CDDSpecialist', True),
    (R.GROUP_OTHERS, 'sig.anadeb@gmail.com', '', True),
    (R.GROUP_OTHERS, 'cosotogosig@gmail.com', '', True),
)

IMPORT_QUESTION = (
    "Importer les {count} adresses des anciennes listes de notification (grm/constants.py), dont "
    "{inactive} inactives, dans la table des destinataires ? [yes/no] "
)
IMPORT_COMMAND = 'python manage.py import_notification_recipients'


def recipient_emails(*groups):
    """Adresses actives des listes `groups`, sans doublon. Lues à chaque envoi : une modification
    faite dans l'admin s'applique dès l'email suivant."""
    emails = R.objects.filter(is_active=True, group__in=groups).order_by('group', 'email').values_list('email', flat=True)
    return list(dict.fromkeys(emails))


def import_legacy_recipients(model=R):
    """Crée les destinataires de `LEGACY_RECIPIENTS` absents de la table. Idempotent : une adresse
    déjà présente dans sa liste n'est jamais modifiée (ses réglages faits dans l'admin sont
    conservés). `model` : modèle historique quand appelé depuis une migration. Renvoie
    `(créés, déjà présents)`."""
    created = existing = 0
    for group, email, role, is_active in LEGACY_RECIPIENTS:
        _obj, was_created = model.objects.get_or_create(
            group=group, email=email, defaults={'role': role, 'is_active': is_active},
        )
        if was_created:
            created += 1
        else:
            existing += 1
    return created, existing


def is_interactive():
    """Vrai seulement si quelqu'un peut répondre au clavier (pas lors d'un déploiement Elastic
    Beanstalk ni des tests)."""
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        return False


def ask_yes_no(question, input_func=None):
    """Pose `question` jusqu'à obtenir oui/non ; sans réponse possible (fin d'entrée), c'est non."""
    input_func = input_func or input
    while True:
        try:
            answer = input_func(question).strip().lower()
        except EOFError:
            return False
        if answer in ('yes', 'y', 'oui', 'o'):
            return True
        if answer in ('no', 'n', 'non'):
            return False


def legacy_import_question():
    inactive = sum(1 for *_rest, is_active in LEGACY_RECIPIENTS if not is_active)
    return IMPORT_QUESTION.format(count=len(LEGACY_RECIPIENTS), inactive=inactive)
