"""Notifications des commentaires d'issue (application mobile, cloche du dashboard web, email).

Seuls les commentaires écrits par un utilisateur (`Comment.is_user_comment`) sont concernés : les
commentaires ajoutés automatiquement par les actions (acceptée, résolue, escaladée...) sont déjà
couverts par les emails de changement de statut (dashboard/tasks.py).

Destinataires d'un commentaire, hors son auteur :
- comptes (notification dans l'application, et email si la case « Envoyer par email » est cochée) :
  participants de l'issue, comptes qui interviennent spécifiquement dans son village (dont les
  membres CVD, FC/AC, FT et SZ du village), comptes ajoutés à la main. Jamais les comptes de portée
  nationale ou plus large que le village (cf. `village_account_ids`) ;
- adresses email seules (si la case est cochée) : listes de l'équipe MGP (admin Django,
  issue/notification_recipients.py) et
  adresses ajoutées à la main.
"""
import logging
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from authentication.models import GovernmentWorker
from grm.my_librairies.mail.send_mail import send_email
from issue.models import Adl, Comment, IssueDepartment, IssueNotification, IssueReadState
from issue.notification_recipients import ALL_GROUPS, recipient_emails

logger = logging.getLogger(__name__)

# Acteurs de terrain mis en copie de toutes les notifications d'une issue (commentaires et emails
# des actions, dashboard/grm/functions.py) quand ils interviennent directement dans son village :
# membres CVD, FC/AC, FT et SZ.
VILLAGE_ACTOR_GROUPS = ('CVGPMembers', 'CommunityFacilitator', 'TechnicalFacilitator', 'Supervisor')
# Nombre de destinataires (copie cachée) par email envoyé : beaucoup de serveurs SMTP limitent le
# nombre de destinataires d'un même message.
EMAIL_BATCH_SIZE = 50
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def bell_cache_key(user_id):
    return f'grm_notifications_bell_{user_id}'


def is_encrypted_text(text):
    """Même convention que le dashboard (grm/issue_detail.html) : un texte chiffré des catégories
    confidentielles est stocké sous la forme d'une représentation `b'...'`."""
    return isinstance(text, str) and "b'" in text


def visible_text(text):
    return '***' if is_encrypted_text(text) else (text or '')


def clean_emails(values):
    """Normalise une liste (ou une chaîne séparée par des virgules, points-virgules ou espaces)
    d'adresses email : minuscules, sans doublon, adresses invalides écartées."""
    if isinstance(values, str):
        values = re.split(r'[,;\s]+', values)
    result = []
    for value in values or []:
        email = str(value or '').strip().lower()
        if email and EMAIL_RE.match(email) and email not in result:
            result.append(email)
    return result


def clean_user_ids(values):
    result = []
    for value in values or []:
        text = str(value).strip()
        if text.isdigit() and int(text) not in result:
            result.append(int(text))
    return result


def _issue_department_id(issue):
    category = issue.category
    if category is None:
        return None
    assigned_department = category.assigned_department_value
    department_id = assigned_department.get('id') if isinstance(assigned_department, dict) else assigned_department
    try:
        return int(department_id) if department_id is not None else None
    except (TypeError, ValueError):
        return None


def _adl_village_ids(adl):
    """Villages d'un `Adl` : union des 4 listes, comme la visibilité du pull mobile
    (sync.views._user_administrative_ids)."""
    ids = set()
    for values in (
        adl.administrative_region_ids_value, adl.smallest_administrative_level_ids_value,
        adl.additional_administrative_region_ids_value,
        adl.additional_smallest_administrative_level_ids_value,
    ):
        ids.update(str(v) for v in (values or []))
    return ids


def village_actor_ids(village_id):
    """Comptes actifs des groupes `VILLAGE_ACTOR_GROUPS` (membres CVD, FC/AC, FT, SZ) qui
    interviennent directement dans le village : il figure dans les villages de l'un de leurs
    `Adl`. Une portée nationale ("1") ne compte pas comme une intervention directe."""
    if not village_id:
        return set()
    village = str(village_id)
    candidates = get_user_model().objects.filter(
        groups__name__in=VILLAGE_ACTOR_GROUPS, is_active=True,
    ).values_list('id', flat=True)
    return {
        adl.representative_id
        for adl in Adl.objects.filter(is_deleted=False, representative_id__in=candidates)
        if village in _adl_village_ids(adl)
    }


def village_actor_emails(village_id):
    """Adresses des acteurs de terrain du village, à mettre en copie des notifications email."""
    return clean_emails(
        get_user_model().objects.filter(id__in=village_actor_ids(village_id)).values_list('email', flat=True)
    )


def participant_account_ids(issue):
    """Assigné, déclarant, chef du département responsable de la catégorie et auteurs des
    commentaires déjà présents sur l'issue."""
    ids = {issue.assignee_id, issue.reporter_id}
    department_id = _issue_department_id(issue)
    if department_id is not None:
        department = IssueDepartment.objects.filter(legacy_id=department_id).first()
        if department:
            ids.add(department.head_id)
    ids.update(
        Comment.objects.filter(issue=issue, is_deleted=False, author__isnull=False)
        .values_list('author_id', flat=True)
    )
    return {i for i in ids if i}


def village_account_ids(issue):
    """Comptes qui interviennent spécifiquement dans le village de l'issue : le village figure
    lui-même dans leur périmètre, soit parmi les villages de leurs `Adl` (dont les membres CVD,
    FC/AC, FT et SZ du village, cf. `village_actor_ids`), soit parmi leurs niveaux d'agent
    (`GovernmentWorker`). Un périmètre plus large (canton, région...) ou national (TOGO) ne suffit
    pas."""
    if not issue.administrative_region_id:
        return set()
    village = str(issue.administrative_region_id)
    user_ids = {
        adl.representative_id
        for adl in Adl.objects.filter(is_deleted=False, representative__isnull=False)
        if village in _adl_village_ids(adl)
    }
    user_ids.update(
        worker.user_id for worker in GovernmentWorker.objects.all()
        if village in {str(v) for v in worker.all_administrative_ids}
    )
    return user_ids


def comment_recipients(comment):
    """Comptes actifs à notifier pour `comment` (auteur exclu)."""
    issue = comment.issue
    ids = participant_account_ids(issue) | village_account_ids(issue) | set(clean_user_ids(comment.notify_user_ids_value))
    ids.discard(comment.author_id)
    User = get_user_model()
    return list(User.objects.filter(id__in=ids, is_active=True))


def comment_email_addresses(comment, recipients):
    emails = clean_emails([u.email for u in recipients] + recipient_emails(*ALL_GROUPS) + comment.notify_emails_value)
    author_email = (comment.author.email or '').strip().lower() if comment.author_id else ''
    return [e for e in emails if e != author_email]


def _format_date(value):
    return timezone.localtime(value).strftime('%d/%m/%Y %H:%M') if value else '-'


def send_comment_email(comment, emails):
    issue = comment.issue
    subject = f"{_('COSO GRM - New comment on an issue')} - {issue.tracking_code} | {issue.internal_code}"
    datas = {
        _("Title"): _("COSO GRM - New comment on an issue"),
        _("Code"): issue.internal_code,
        _("Tracking code"): issue.tracking_code or '-',
        _("Category"): issue.category.name if issue.category else '-',
        _("Type"): issue.issue_type.name if issue.issue_type else '-',
        _("Status"): issue.status.name if issue.status else '-',
        _("Description"): visible_text(issue.description),
        _("Date of the issue"): _format_date(issue.issue_date),
        _("Intake date"): _format_date(issue.intake_date),
        _("Location"): issue.administrative_region_name or '-',
        _("Assigned to"): issue.assignee_name or '-',
        _("Reporter"): issue.reporter_name or '-',
        _("Comment by"): comment.author_name or '-',
        _("Comment"): visible_text(comment.comment),
    }
    context = {
        "datas": datas,
        "url": f"{settings.GRM_URL_BASE}/grm/issue-detail/{issue.auto_increment_id}/",
    }
    for start in range(0, len(emails), EMAIL_BATCH_SIZE):
        send_email(subject, "mail/send/comment", dict(context), [], cc=[], bcc=emails[start:start + EMAIL_BATCH_SIZE])


def notify_comment(comment):
    """Crée les notifications de `comment` et envoie l'email. Ne fait rien si un autre appel l'a
    déjà pris en charge (le marquage est atomique : plusieurs synchronisations mobiles peuvent
    déclencher ce traitement en même temps)."""
    now = timezone.now()
    claimed = Comment.objects.filter(pk=comment.pk, notifications_processed_at__isnull=True).update(
        notifications_processed_at=now,
    )
    if not claimed:
        return []

    recipients = comment_recipients(comment)
    issue = comment.issue
    IssueNotification.objects.bulk_create(
        [
            IssueNotification(
                recipient=user, issue=issue, comment=comment, kind=IssueNotification.KIND_COMMENT,
                issue_code=issue.internal_code, comment_text=visible_text(comment.comment),
                author_name=comment.author_name,
            )
            for user in recipients
        ],
        ignore_conflicts=True,
    )
    for user in recipients:
        cache.delete(bell_cache_key(user.id))

    if comment.send_email:
        emails = comment_email_addresses(comment, recipients)
        if emails:
            send_comment_email(comment, emails)
    return recipients


def send_comment_notifications(comment_ids=None):
    """Traite les commentaires écrits pas encore notifiés (tous, ou seulement `comment_ids`)."""
    queryset = Comment.objects.filter(
        is_user_comment=True, notifications_processed_at__isnull=True, is_deleted=False,
        issue__is_deleted=False, issue__confirmed=True,
    ).select_related('issue', 'issue__category', 'issue__status', 'issue__issue_type', 'author')
    if comment_ids is not None:
        queryset = queryset.filter(id__in=list(comment_ids))
    for comment in queryset.order_by('created_at'):
        try:
            notify_comment(comment)
        except Exception:
            logger.exception('Notification du commentaire %s impossible', comment.pk)


def mark_issue_read(user, issue):
    """Ouverture d'une issue : elle n'est plus « non lue » et ses notifications sont lues
    (`updated_at` mis à jour pour que le pull propage la lecture vers le mobile)."""
    now = timezone.now()
    IssueReadState.objects.update_or_create(user=user, issue=issue, defaults={'last_read_at': now})
    IssueNotification.objects.filter(recipient=user, issue=issue, read_at__isnull=True).update(
        read_at=now, updated_at=now,
    )
    cache.delete(bell_cache_key(user.id))


def apply_notification_read_push(user, table_changes):
    """Table `issue_notifications` d'un push WatermelonDB : le mobile ne fait que marquer ses
    propres notifications comme lues. Renvoie les ids refusés (inconnus ou d'un autre compte),
    que le mobile retire de sa base locale."""
    rejected = []
    records = list(table_changes.get('created', [])) + list(table_changes.get('updated', []))
    now = timezone.now()
    for record in records:
        notification_id = record.get('id')
        try:
            notification = IssueNotification.objects.filter(pk=notification_id, recipient=user).first()
        except Exception:
            notification = None
        if notification is None:
            if notification_id:
                rejected.append(notification_id)
            continue
        if record.get('read_at') and notification.read_at is None:
            IssueNotification.objects.filter(pk=notification.pk).update(read_at=now, updated_at=now)
            cache.delete(bell_cache_key(user.id))
    return rejected


def unread_comment_notifications(user):
    return IssueNotification.objects.filter(recipient=user, read_at__isnull=True, is_deleted=False)


def pull_visibility_filters(user):
    """Filtres `Q()` par table WatermelonDB, appliqués par sync.views.PullView."""
    return {'issue_notifications': Q(recipient=user)}
