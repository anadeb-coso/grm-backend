from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _
from twilio.base.exceptions import TwilioRestException

from authentication.models import (
    anonymize_issue_data, get_assignee, get_adl_to_escalate, get_cvgp_member_escalation_replacement_assignee,
)
from dashboard.grm import CHOICE_CONTACT, CHOICE_PHONE
from dashboard.grm.serializers import issue_to_legacy_dict
from grm.celery import app
from sms_client import send_sms
from dashboard.grm.functions import (
    send_notification_by_mail, send_notification_on_escalation_by_mail,
    send_issue_status_update_notification_by_mail, send_assignee_notification_by_mail,
)
from issue.models import Comment, EscalationLevel, Issue, IssueStatus, IssueStatusStory
from administrativelevels.models import AdministrativeLevel
from grm.call_objects_from_other_db import mis_objects_call


@app.task
def check_issues():
    """
    Auto-complète/nettoie les issues confirmées auxquelles il manque un assignee, un internal_code,
    ou dont les données citoyen/contact n'ont pas encore été anonymisées. Équivalent Postgres de
    l'ancienne tâche CouchDB (`auto_increment_id` n'est plus jamais manquant : c'est un champ
    obligatoire du modèle `Issue`, renseigné dès la création — cf. StartNewIssueView).
    """
    result = {
        'errors': [], 'auto_increment_id_updated': [], 'internal_code_updated': [],
        'anonymized_data': [], 'assignee_updated': [],
    }
    updated_issues = 0

    candidates = Issue.objects.filter(confirmed=True, is_deleted=False).filter(
        Q(assignee__isnull=True)
        | Q(internal_code='') | Q(internal_code__startswith='DRAFT-')
        | (~Q(citizen__isnull=True) & ~Q(citizen='') & ~Q(citizen='*'))
        | (Q(contact_information__contact__isnull=False) & ~Q(contact_information__contact='') & ~Q(contact_information__contact='*'))
    ).select_related('category')

    for issue in candidates:
        issue_id = str(issue.pk)
        changed_fields = set()

        if not issue.assignee_id:
            try:
                assignee = get_assignee(issue)
                if assignee:
                    issue.assignee_id = assignee['id']
                    issue.assignee_name = assignee['name']
                    changed_fields |= {'assignee', 'assignee_name'}
                    result['assignee_updated'].append(issue_id)
            except Exception:
                result['errors'].append(f'Error trying to set assignee for issue document with id {issue_id}')

        if not issue.internal_code or issue.internal_code.startswith('DRAFT-'):
            try:
                administrative_id = issue.administrative_region_id
                issue.internal_code = f'{issue.category.abbreviation}-{administrative_id}-{issue.auto_increment_id}'
                changed_fields.add('internal_code')
                result['internal_code_updated'].append(issue_id)
            except Exception:
                result['errors'].append(f'Error trying to set internal_code for issue document with id {issue_id}')

        needs_anonymizing = (issue.citizen and issue.citizen != '*') or (
            issue.contact_information and issue.contact_information.get('contact') not in (None, '', '*')
        )
        if needs_anonymizing:
            try:
                legacy = {
                    '_id': issue_id, 'citizen': issue.citizen, 'contact_information': issue.contact_information,
                }
                anonymize_issue_data(legacy)
                issue.citizen = legacy['citizen']
                issue.contact_information = legacy['contact_information']
                changed_fields |= {'citizen', 'contact_information'}
                result['anonymized_data'].append(issue_id)
            except Exception:
                result['errors'].append(f'Error trying to anonymize issue document with id {issue_id}')

        if changed_fields:
            # `updated_at` doit être explicitement dans `update_fields` : Django n'applique
            # `auto_now` que pour les champs listés (sinon la ligne change en base sans que le
            # pull incrémental mobile ne le détecte jamais, cf. dashboard/grm/serializers.py::
            # LegacyIssueDoc.save() pour le même correctif appliqué au dashboard web).
            issue.save(update_fields=list(changed_fields) + ['updated_at'])
            updated_issues += 1

    result['updated_issues'] = updated_issues
    return result


@app.task
def escalate_issues():
    """
    Pour toute issue en cours d'escalade (`escalate_flag=True`), s'assure qu'un `EscalationLevel`
    a bien été résolu (normalement déjà fait de façon synchrone par
    `dashboard/grm/views.py::SubmitIssueEscalateFormView`, cf. Phase 6 de la migration — ce filet
    de sécurité couvre les données plus anciennes ou une erreur transitoire), puis lève le drapeau
    d'escalade, rouvre l'issue et notifie par email.
    """
    result = {'errors': [], 'issues_updated': [], 'scale_is_not_available': []}
    updated_issues = 0

    # Reparer administrative_id = None
    candidates_escalated = Issue.objects.filter(
        confirmed=True, is_deleted=False, assignee__isnull=False, 
        escalation_levels__administrative_level__isnull=False, 
        escalation_levels__name__isnull=False, 
        escalation_levels__administrative_id__isnull=True
    ).select_related('category', 'status')
    for _issue in candidates_escalated:
        for current_level in _issue.escalation_levels.filter(administrative_level__isnull=False, name__isnull=False, administrative_id__isnull=True):
            if current_level and not current_level.administrative_id and (
                current_level.administrative_level and current_level.name
            ):
                _adl = mis_objects_call.filter_objects(AdministrativeLevel, name=current_level.name, type=current_level.administrative_level).first()
                if _adl:
                    current_level.administrative_id = _adl.id
                    current_level.save(update_fields=['administrative_id', 'updated_at'])
                    # print(current_level.name)
                    # print(current_level.administrative_id)
                    # print(current_level.administrative_level)


    candidates = Issue.objects.filter(
        confirmed=True, is_deleted=False, assignee__isnull=False, escalate_flag=True
    ).select_related('category', 'status', 'assignee')
    open_status = IssueStatus.objects.filter(open_status=True).first()
    for issue in candidates:
        issue_id = str(issue.pk)
        try:
            current_level = issue.escalation_levels.order_by('-created_at').first()
            if not current_level:
                escalate_to = get_adl_to_escalate(issue.administrative_region_id) if issue.administrative_region_id else None
                if escalate_to:
                    EscalationLevel.objects.create(
                        issue=issue,
                        administrative_level=escalate_to['administrative_level'],
                        administrative_id=escalate_to['administrative_id'],
                        name=escalate_to['name'],
                        due_at=timezone.now(),
                    )
                    current_level = issue.escalation_levels.order_by('-created_at').first()

            if current_level:

                # Une issue suivie par un membre CVGP (`CVGPMembers`) qui vient de quitter le
                # niveau Village pour le niveau supérieur (Canton — c'est-à-dire qu'aucun autre
                # `EscalationLevel` n'existait avant celui-ci) ne doit plus rester assignée à ce
                # membre CVGP (il n'a plus la main dessus une fois remontée, cf. §CVGP côté mobile).
                # On la réassigne au premier profil disponible dans l'ordre de repli
                # CommunityFacilitator -> Supervisor (village) -> Safeguard (national), et on
                # notifie ce nouvel assigné.
                just_left_village_level = (
                    current_level.administrative_level == 'Canton'
                    and not issue.escalation_levels.exclude(pk=current_level.pk).exists()
                )
                if (
                    just_left_village_level and issue.assignee_id
                    and issue.assignee.groups.filter(name='CVGPMembers').exists()
                ):
                    replacement_assignee = get_cvgp_member_escalation_replacement_assignee(
                        issue.administrative_region_id
                    )
                    if replacement_assignee:
                        issue.assignee = replacement_assignee
                        issue.assignee_name = replacement_assignee.name
                        # cf. check_issues() ci-dessus : `updated_at` doit être explicitement
                        # listé pour que le pull incrémental mobile détecte la réassignation.
                        issue.save(update_fields=['assignee', 'assignee_name', 'updated_at'])
                        try:
                            send_assignee_notification_by_mail(
                                issue_to_legacy_dict(issue), replacement_assignee,
                            )
                        except Exception:
                            pass

                issue.escalate_flag = False
                update_fields = ['escalate_flag']
                if open_status:
                    issue.status = open_status
                    update_fields.append('status')
                # cf. check_issues() ci-dessus : `updated_at` doit être explicitement listé pour
                # que Django l'auto-rafraîchisse, sinon la ré-ouverture automatique de l'issue
                # (statut + escalate_flag) ne remonte jamais au pull mobile.
                issue.save(update_fields=update_fields + ['updated_at'])

                IssueStatusStory.objects.create(
                    issue=issue, status=open_status, user=None, user_full_name="GRM System",
                    comment=_("Automatic update"), datetime=timezone.now(),
                )
                Comment.objects.create(
                    issue=issue, author=None, author_name="GRM System",
                    comment=_("Issue opened"), due_at=timezone.now(),
                )

                result['issues_updated'].append(issue_id)
                updated_issues += 1

                try:
                    send_notification_on_escalation_by_mail(issue_to_legacy_dict(issue))
                except Exception:
                    pass
            else:
                result['scale_is_not_available'].append(issue_id)

        except Exception:
            result['errors'].append(f'Error trying to escalate for issue document with id {issue_id}')

    result['updated_issues'] = updated_issues
    return result


@app.task
def send_sms_message():
    messages = {
        'accepted_alert_message': _(
            "Your issue submitted has been accepted into the system with the code %s(tracking_code)s"),
        'rejected_alert_message': _(
            "Your issue %s(tracking_code)s has been rejected with the following response: %s(reason)s"),
        'closed_alert_message': _(
            "Your issue %s(tracking_code)s has been resolved with the following response: %s(resolution)s"),
    }

    candidates = Issue.objects.filter(
        confirmed=True, is_deleted=False,
        assignee__isnull=False, tracking_code__isnull=False,
        contact_medium=CHOICE_CONTACT,
        contact_information__type=CHOICE_PHONE,
    ).exclude(tracking_code='').filter(
        Q(accepted_alert_sent=False) | Q(rejected_alert_sent=False) | Q(closed_alert_sent=False)
    ).select_related('status')

    result = {'errors': [], 'notified_issues': []}
    updated_issues = 0

    for issue in candidates:
        issue_id = str(issue.pk)
        phone = (issue.contact_information or {}).get('contact')
        if not phone:
            continue

        notified = False
        update_fields = []

        if not issue.accepted_alert_sent and issue.status and issue.status.open_status:
            msg = messages['accepted_alert_message'] % {'tracking_code': issue.tracking_code}
            try:
                send_sms(phone, msg)
                issue.accepted_alert_sent = True
                update_fields.append('accepted_alert_sent')
                notified = True
            except TwilioRestException as e:
                result['errors'].append(e.msg)

        if not issue.rejected_alert_sent and issue.status and issue.status.rejected_status:
            # `reject_reason` n'a pas de colonne Postgres dédiée (cf. dashboard/grm/serializers.py
            # ::_IGNORED_ON_SAVE) — le motif reste consultable dans l'historique des commentaires.
            msg = messages['rejected_alert_message'] % {
                'tracking_code': issue.tracking_code, 'reason': '',
            }
            try:
                send_sms(phone, msg)
                issue.rejected_alert_sent = True
                update_fields.append('rejected_alert_sent')
                notified = True
            except TwilioRestException as e:
                result['errors'].append(e.msg)

        if not issue.closed_alert_sent and issue.status and issue.status.final_status:
            msg = messages['closed_alert_message'] % {
                'tracking_code': issue.tracking_code, 'resolution': issue.research_result or '',
            }
            try:
                send_sms(phone, msg)
                issue.closed_alert_sent = True
                update_fields.append('closed_alert_sent')
                notified = True
            except TwilioRestException as e:
                result['errors'].append(e.msg)

        if notified:
            # cf. check_issues() ci-dessus.
            issue.save(update_fields=update_fields + ['updated_at'])
            updated_issues += 1
            result['notified_issues'].append(issue_id)

    result['updated_issues'] = updated_issues
    return result


@app.task
def send_a_new_issue_notification():
    """Envoie la notification email de création aux issues confirmées pas encore notifiées."""
    candidates = Issue.objects.filter(
        confirmed=True, is_deleted=False, notification_send=False,
    ).select_related('status', 'category', 'age_group', 'issue_type').prefetch_related(
        'comments', 'reasons', 'escalation_reasons', 'escalation_levels', 'issue_status_stories', 'attachments',
    )
    for issue in candidates:
        try:
            send_notification_by_mail(issue_to_legacy_dict(issue))
            issue.notification_send = True
            # cf. check_issues() ci-dessus.
            issue.save(update_fields=['notification_send', 'updated_at'])
        except Exception:
            continue


@app.task
def send_issue_status_notifications():
    """Notifie par email chaque étape du traitement d'une issue : ouverture/acceptation,
    investigation/décision, résolution. Se base sur `IssueStatusStory.email_notified=False`
    plutôt que sur un drapeau par `Issue` (comme `accepted_alert_sent`/`closed_alert_sent` pour le
    SMS) car une même issue peut accumuler plusieurs entrées d'investigation
    (`IssueActions/containers/Content.js::recordStep()`), chacune devant déclencher son propre
    email. Le type d'email est déduit du statut de l'entrée : `open_status` -> ouverture,
    `final_status` -> résolution, tout le reste (investigation, mais aussi rejet/non-résolution
    qui n'ont pas de canal dédié) -> investigation/décision."""
    result = {'errors': [], 'notified': []}

    candidates = IssueStatusStory.objects.filter(
        email_notified=False, issue__is_deleted=False, issue__confirmed=True,
    ).select_related(
        'status', 'issue', 'issue__status', 'issue__category', 'issue__age_group', 'issue__issue_type',
    ).prefetch_related(
        'issue__comments', 'issue__reasons', 'issue__escalation_reasons', 'issue__escalation_levels',
        'issue__issue_status_stories', 'issue__attachments',
    ).order_by('created_at')

    for story in candidates:
        story_id = str(story.pk)
        try:
            if story.status.open_status and not story.issue.issue_status_stories.filter(email_notified=True).exists():
                kind = 'opened'
            elif story.status.final_status:
                kind = 'resolved'
            elif story.status.rejected_status:
                kind = 'rejected'
            else:
                kind = 'investigation'

            send_issue_status_update_notification_by_mail(
                issue_to_legacy_dict(story.issue), kind, story_comment=story.comment,
            )
            story.email_notified = True
            # cf. check_issues() ci-dessus : même correctif pour `IssueStatusStory`.
            story.save(update_fields=['email_notified', 'updated_at'])
            result['notified'].append(story_id)
        except Exception:
            result['errors'].append(f'Error trying to send status notification for issue_status_story with id {story_id}')

    return result
