from django.utils.translation import gettext_lazy as _
from django.db.models import Q
from datetime import datetime, timedelta
from django.conf import settings
import pandas as pd
from io import BytesIO
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from django.utils import timezone
import os
from sys import platform

from grm.utils import datetime_str
from grm.my_librairies.mail.send_mail import send_email
from issue.models import NotificationRecipient
from issue.notification_recipients import recipient_emails
from dashboard.grm import CHOICE_EMAIL
from administrativelevels.models import AdministrativeLevel
from grm.my_librairies.functions import strip_accents
from grm.call_objects_from_other_db import mis_objects_call
from client import get_db
from grm.utils import get_administrative_level_descendants_using_mis
from issue.models import Issue, Wave


COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE
COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL = settings.COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL

# Mêmes valeurs que `dashboard/grm/views.py::ISSUE_SELECT_RELATED`/`ISSUE_PREFETCH_RELATED`
# (dupliquées ici, comme `issue/views_rest.py::ISSUE_SELECT_RELATED`, pour éviter un import
# circulaire : `dashboard.grm.views` importe déjà ce module au niveau module).
ISSUE_SELECT_RELATED = ('status', 'category', 'age_group', 'issue_type')
ISSUE_PREFETCH_RELATED = (
    'comments', 'reasons', 'reasons__attachment', 'escalation_reasons', 'escalation_reasons__attachment',
    'escalation_levels', 'issue_status_stories', 'issue_status_stories__status', 'issue_status_stories__user',
    'attachments',
)


def get_multiple_values(query_dict, name):
    """Valeurs d'un filtre à choix multiple : `name=1,3`, `name=1&name=3` ou `name[]=1&name[]=3`
    (sérialisation jQuery des tableaux). Une seule valeur (`name=1`) reste acceptée, comme avant."""
    values = []
    for raw in query_dict.getlist(name) + query_dict.getlist(f'{name}[]'):
        for value in str(raw).split(','):
            value = value.strip()
            if value and value not in values:
                values.append(value)
    return values


def int_values(values):
    """Les valeurs entières d'une liste (ids) ; les autres sont ignorées."""
    return [int(v) for v in values if str(v).strip().isdigit()]


def get_waves(query_dict):
    """Vagues sélectionnées (paramètre `wave`, une ou plusieurs)."""
    ids = int_values(get_multiple_values(query_dict, 'wave'))
    return list(Wave.objects.filter(id__in=ids).order_by('id')) if ids else []


def waves_administrative_ids(waves):
    """Union (sans doublon, ordre conservé) des `administrative_ids` des vagues."""
    result, seen = [], set()
    for wave_object in waves:
        for elt in wave_object.administrative_ids or []:
            if str(elt) not in seen:
                seen.add(str(elt))
                result.append(elt)
    return result


def build_issue_queryset(request):
    """Équivalent Postgres du sélecteur Mango CouchDB historique construit par l'ancienne
    `export_issues` (toujours plus bas dans ce fichier, non encore migrée) : même logique de
    visibilité par rôle et mêmes filtres (`start_date`/`end_date`/`code`/`assigned_to`/
    `category`/`status`/`other`/`region`/`reported_by`/`publish`/`wave`), mais renvoyant un
    `QuerySet` Django plutôt qu'une liste de documents CouchDB. Voir aussi
    `issue/views_rest.py::RestGetIssues`, qui implémente la même logique pour l'API REST
    historique (paramètres de requête différents, pas de notion de "wave" côté mobile) : gardée
    séparée exprès (cf. sa docstring), donc toute correction de bug ici doit être reportée là-bas
    si elle s'applique.

    Utilisée par `dashboard.grm.views.IssueListView.get_results`. Retourne
    `(queryset, wave_administrative_ids)` : `wave_administrative_ids` est la liste brute (telle
    que stockée sur `Wave.administrative_ids`) utilisée ensuite pour les statistiques par village
    de la vague sélectionnée."""
    get = request.GET
    start_date = get.get('start_date')
    end_date = get.get('end_date')
    code = get.get('code')
    # Filtres à choix multiple (MultipleSearchIssueForm) : une ou plusieurs valeurs.
    assigned_to = int_values(get_multiple_values(get, 'assigned_to'))
    category = int_values(get_multiple_values(get, 'category'))
    issue_status = int_values(get_multiple_values(get, 'status'))
    other = get_multiple_values(get, 'other')
    region = get.get('region')
    reported_by = int_values(get_multiple_values(get, 'reported_by'))
    publish = {v for v in get_multiple_values(get, 'publish') if v in ('True', 'False')}
    waves = get_waves(get)
    user = request.user

    queryset = Issue.objects.select_related(*ISSUE_SELECT_RELATED).prefetch_related(*ISSUE_PREFETCH_RELATED).filter(
        confirmed=True, is_deleted=False, auto_increment_id__isnull=False,
    )

    # Vague(s) : villages de la vague ET période de la vague ; plusieurs vagues = l'une OU
    # l'autre. Avec une seule vague, même résultat qu'avant (les dates saisies, filtrées plus bas,
    # restent bornées par celles de la vague).
    wave_administrative_ids = waves_administrative_ids(waves)
    if waves:
        waves_q = Q()
        for wave_object in waves:
            wave_q = Q(administrative_region_id__in=int_values(wave_object.administrative_ids))
            if wave_object.begin:
                wave_q &= Q(intake_date__gte=wave_object.begin)
            if wave_object.end:
                wave_q &= Q(intake_date__lt=wave_object.end + timedelta(days=1))
            waves_q |= wave_q
        queryset = queryset.filter(waves_q)

    if user.groups.filter(name__in=["Admin", "ViewerOfAllIssues"]).exists():
        pass
    elif hasattr(user, 'governmentworker') and user.governmentworker.administrative_id != "1":
        parent_ids = user.governmentworker.all_administrative_ids
        descendants = []
        for p_id in parent_ids:
            descendants += get_administrative_level_descendants_using_mis(None, p_id, [], user)
        allowed_regions = descendants + parent_ids
        if wave_administrative_ids:
            allowed_regions = list(
                set(str(elt) for elt in allowed_regions) & set(str(elt) for elt in wave_administrative_ids)
            )
        allowed_regions_int = [int(elt) for elt in allowed_regions if str(elt).isdigit()]

        queryset = queryset.filter(
            Q(assignee_id=user.id) | Q(
                category__assigned_department__id=user.governmentworker.department,
                administrative_region_id__in=allowed_regions_int,
            )
        )
    else:
        # Les issues assignées à l'utilisateur restent visibles même non publiées : il doit
        # pouvoir les traiter sur le web comme sur le mobile.
        queryset = queryset.filter(Q(publish=True) | Q(assignee_id=user.id))

    if start_date:
        queryset = queryset.filter(intake_date__gte=datetime.strptime(start_date, '%d/%m/%Y').date())
    if end_date:
        queryset = queryset.filter(
            intake_date__lt=datetime.strptime(end_date, '%d/%m/%Y').date() + timedelta(days=1)
        )

    if code:
        queryset = queryset.filter(
            Q(internal_code__icontains=code) | Q(tracking_code__icontains=code) | Q(description__icontains=code)
        )
    if assigned_to:
        queryset = queryset.filter(assignee_id__in=assigned_to)
    if category:
        queryset = queryset.filter(category__legacy_id__in=category)
    if issue_status:
        queryset = queryset.filter(status__legacy_id__in=issue_status)
    if 'Escalate' in other:
        queryset = queryset.filter(escalation_reasons__isnull=False).distinct()
    if reported_by:
        queryset = queryset.filter(reporter_id__in=reported_by)
    if len(publish) == 1:  # « Publiée » et « Non publiée » ensemble = pas de filtre
        queryset = queryset.filter(publish=('True' in publish))

    if region:
        filter_regions = get_administrative_level_descendants_using_mis(None, region, [], user) + [str(region)]
        if wave_administrative_ids:
            filter_regions = list(set(filter_regions) & set(str(elt) for elt in wave_administrative_ids))
        filter_regions_int = [int(elt) for elt in filter_regions if str(elt).isdigit()]
        queryset = queryset.filter(administrative_region_id__in=filter_regions_int)

    queryset = queryset.order_by('-created_date')

    return queryset, wave_administrative_ids


BELL_CACHE_SECONDS = 60
BELL_LIST_SIZE = 5
PUBLISHER_GROUPS = ('Admin', 'Safeguard')


def get_notifications_bell_summary(request):
    """Contenu de la cloche du dashboard pour `request.user`, sur son périmètre (mêmes issues que la
    page « Review Issues », `build_issue_queryset` sans filtre) :
    - issues non lues : créées ou modifiées (changement de statut) depuis sa dernière ouverture,
      et après le début de son suivi (`NotificationBaseline`, posé à sa première consultation) ;
    - issues avec de nouveaux commentaires : ses notifications de commentaire non lues ;
    - issues non publiées, pour les comptes autorisés à publier ;
    - nombre d'issues non démarrées, en cours et non résolues.
    Mis en cache par utilisateur (invalidé à la lecture d'une issue et à chaque notification)."""
    from django.core.cache import cache
    from django.db.models import Count, F, Max, OuterRef, Subquery
    from django.db.models.functions import Coalesce, Greatest
    from django.utils import timezone

    from issue.deadlines import overdue_by_village, overdue_issues
    from issue.models import IssueNotification, IssueReadState, IssueStatusStory, NotificationBaseline
    from issue.notifications import bell_cache_key

    user = request.user
    cached = cache.get(bell_cache_key(user.id))
    if cached is not None:
        return cached

    perimeter, _ = build_issue_queryset(request)
    perimeter = perimeter.select_related(None).prefetch_related(None).order_by()
    since = NotificationBaseline.objects.get_or_create(user=user, defaults={'since': timezone.now()})[0].since

    last_read = IssueReadState.objects.filter(user=user, issue=OuterRef('pk')).values('last_read_at')[:1]
    last_status_change = IssueStatusStory.objects.filter(
        issue=OuterRef('pk'), is_deleted=False,
    ).order_by('-created_at').values('created_at')[:1]
    unread = perimeter.annotate(
        last_read=Subquery(last_read), last_status_change=Subquery(last_status_change),
    ).annotate(
        activity=Greatest('created_at', Coalesce('last_status_change', 'created_at')),
    ).filter(activity__gt=since).filter(Q(last_read__isnull=True) | Q(activity__gt=F('last_read')))

    unread_comments = IssueNotification.objects.filter(
        recipient=user, read_at__isnull=True, is_deleted=False, issue__is_deleted=False,
    )

    counts = perimeter.aggregate(
        not_started=Count('pk', filter=Q(status__initial_status=True)),
        in_progress=Count('pk', filter=Q(
            status__isnull=False, status__initial_status=False, status__final_status=False,
            status__rejected_status=False, status__unresolved_status=False,
        )),
        unresolved=Count('pk', filter=Q(status__unresolved_status=True)),
        unpublished=Count('pk', filter=Q(publish=False)),
    )
    can_publish = user.groups.filter(name__in=PUBLISHER_GROUPS).exists()

    # Plaintes en retard (délai de traitement du niveau dépassé), regroupées par village.
    late, late_infos = overdue_issues(perimeter)
    late_villages = overdue_by_village([issue for issue, _info in late], late_infos)

    summary = {
        'unread_count': unread.count(),
        'unread_issues': list(
            unread.order_by('-activity').values('auto_increment_id', 'internal_code', 'activity')[:BELL_LIST_SIZE]
        ),
        'commented_count': unread_comments.values('issue').distinct().count(),
        'commented_issues': list(
            unread_comments.values('issue__auto_increment_id', 'issue_code')
            .annotate(unread=Count('id'), last=Max('created_at')).order_by('-last')[:BELL_LIST_SIZE]
        ),
        'can_publish': can_publish,
        'unpublished_count': counts['unpublished'] if can_publish else 0,
        'not_started_count': counts['not_started'],
        'in_progress_count': counts['in_progress'],
        'unresolved_count': counts['unresolved'],
        'overdue_count': len(late),
        'overdue_villages': late_villages[:BELL_LIST_SIZE],
        'overdue_villages_count': len(late_villages),
    }
    summary['badge_count'] = (
        summary['unread_count'] + summary['commented_count'] + summary['unpublished_count']
        + summary['overdue_villages_count']
    )
    cache.set(bell_cache_key(user.id), summary, BELL_CACHE_SECONDS)
    return summary

def get_issue_status_stories(user, doc, status):
    issue_status_stories = doc["issue_status_stories"] if doc.get("issue_status_stories") else []
    
    issue_status_stories.insert(0, {
        'status': status,
        'user': {
            'id': user.id,
            'username': user.username,
            'full_name': user.get_full_name()
        },
        "comment": doc.get('_comment'),
        'datetime': datetime_str()
    })

    return issue_status_stories


# Listes de l'équipe MGP (admin Django, issue.models.NotificationRecipient), lues à chaque envoi.
def _safeguard_specialist_emails():
    return recipient_emails(NotificationRecipient.GROUP_SAFEGUARD_SPECIALISTS)


def _team_email_cc():
    """Copie des emails de nouvelle issue, d'escalade et de changement de statut."""
    return recipient_emails(
        NotificationRecipient.GROUP_COORDINATORS, NotificationRecipient.GROUP_REGIONAL_COORDINATORS,
        NotificationRecipient.GROUP_SAFEGUARD_ASSISTANTS, NotificationRecipient.GROUP_OTHER_SPECIALISTS,
        NotificationRecipient.GROUP_ANADEB, NotificationRecipient.GROUP_OTHERS,
    )


def _assignment_team_email_cc():
    """Copie de l'email d'assignation."""
    return recipient_emails(
        NotificationRecipient.GROUP_REGIONAL_COORDINATORS, NotificationRecipient.GROUP_SAFEGUARD_ASSISTANTS,
        NotificationRecipient.GROUP_OTHERS,
    )


def _citizen_email_cc(issue):
    """Le plaignant n'est mis en copie des notifications email d'une issue que s'il a choisi
    l'email comme moyen de contact lors de l'enregistrement (`contact_information.type ==
    CHOICE_EMAIL`, même convention que `dashboard/tasks.py::send_sms_message` pour le SMS)."""
    contact_information = issue.get('contact_information') or {}
    if contact_information.get('type') == CHOICE_EMAIL:
        contact = contact_information.get('contact')
        if contact:
            return [contact]
    return []


def _village_actors_email_cc(issue):
    """Acteurs de terrain qui interviennent directement dans le village de l'issue (membres CVD,
    FC/AC, FT, SZ), mis en copie de toutes les notifications email de l'issue, comme les
    notifications de commentaire (issue/notifications.py::village_actor_ids)."""
    from issue.notifications import village_actor_emails

    region = issue.get('administrative_region') or {}
    village_id = region.get('administrative_id') if isinstance(region, dict) else region
    try:
        return village_actor_emails(village_id)
    except Exception:
        return []


def send_notification_by_mail(issue):
    try:
        return send_email(
            f"{_('COSO GRM - A new issue recorded')} - {issue['tracking_code']} | {issue['internal_code']}",
            "mail/send/comment",
            {
                "datas": {
                    _("Title"): _("COSO GRM - A new issue recorded"),
                    _("Code"): issue['internal_code'],
                    _("Category"): issue['category']['name'],
                    _("Description"): "***" if "b'" in issue['description'] else issue['description'],
                    _("Date of incident/complaint"): issue.get('issue_date'),
                    _("Date of registration"): issue.get('created_date'),
                    _("Level"): issue['escalation_administrativelevels'][0]['escalate_to']['administrative_level'] \
                        if 'escalation_administrativelevels' in issue and issue['escalation_administrativelevels'] else \
                            issue['category']['administrative_level'],
                    _("Source"): issue['source'],
                },
                "user": {
                    _("Reporter"): issue['reporter']['name']
                },
                "url": f"{settings.GRM_URL_BASE}/grm/issue-detail/{issue['auto_increment_id']}/",
                'current_year': datetime.now().year,
            },
            _safeguard_specialist_emails(),
            cc=_team_email_cc() + _citizen_email_cc(issue) + _village_actors_email_cc(issue)
        )
    except:
        return None

def send_notification_on_escalation_by_mail(issue):
    try:
        return send_email(
            f"{_('COSO GRM - A new issue scaled')} - {issue['tracking_code']} | {issue['internal_code']}",
            "mail/send/comment",
            {
                "datas": {
                    _("Title"): _("COSO GRM - A new issue scaled"),
                    _("Code"): issue['internal_code'],
                    _("Category"): issue['category']['name'],
                    _("Description"): "***" if "b'" in issue['description'] else issue['description'],
                    _("Up to level"): issue['escalation_administrativelevels'][0]['escalate_to']['administrative_level'],
                    _("Comment on the unresolution"): issue['unresolved_reason']['comment'] if issue.get('unresolved_reason') else '-',
                    _("Unresolution date"): issue['unresolved_reason']['due_at'] if issue.get('unresolved_reason') else '-',
                    _("Comments on the scalation"): issue['escalate_reason']['comment'] if issue.get('escalate_reason') else '-',
                    _("Scalation date"): issue['escalate_reason']['due_at'] if issue.get('escalate_reason') else '-'
                },
                "user": {
                    _("Assigned to"): issue['assignee']['name']
                },
                "url": f"{settings.GRM_URL_BASE}/grm/issue-detail/{issue['auto_increment_id']}/",
                'current_year': datetime.now().year,
            },
            _safeguard_specialist_emails(),
            cc=_team_email_cc() + _citizen_email_cc(issue) + _village_actors_email_cc(issue)
        )
    except:
        return None



def send_assignee_notification_by_mail(issue, user):
    try:
        return send_email(
            f"{_('COSO GRM - You have been assigned a issue')} - {issue['tracking_code']} | {issue['internal_code']}",
            "mail/send/comment",
            {
                "datas": {
                    _("Title"): _("COSO GRM - You have been assigned a issue"),
                    _("Code"): issue['internal_code'],
                    _("Category"): issue['category']['name'],
                    _("Description"): "***" if "b'" in issue['description'] else issue['description'],
                    _("Level"): issue['escalation_administrativelevels'][0]['escalate_to']['administrative_level'] \
                        if 'escalation_administrativelevels' in issue and issue['escalation_administrativelevels'] else \
                            issue['category']['administrative_level'],
                    _("Source"): issue['source'],
                },
                "user": {
                    _("Reporter"): issue['reporter']['name'],
                    _("Assigned to"): issue['assignee']['name']
                },
                "user_full_name": f"{user.first_name} {user.last_name}",
                "comment":  _("Please find below the information concerning the new issue that has just been assigned to you."), 
                "greeting":  _("Hello"),
                "all_sex":  _("Mr./Mrs."),
                "url": f"{settings.GRM_URL_BASE}/grm/issue-detail/{issue['auto_increment_id']}/",
                'current_year': datetime.now().year,
            },
            [user.email],
            cc=_assignment_team_email_cc() + _citizen_email_cc(issue) + _village_actors_email_cc(issue)
        )
    except:
        return None


def send_issue_status_update_notification_by_mail(issue, kind, story_comment=None):
    """Notifie par email l'évolution du statut d'une issue — trois cas demandés explicitement :
    ouverture/acceptation (`kind='opened'`), investigation/décision (`kind='investigation'`,
    déclenché par chaque entrée `IssueStatusStory` qui ne correspond ni à une ouverture ni à une
    résolution — ex. `IssueActions/containers/Content.js::recordStep()`), et résolution
    (`kind='resolved'`). Voir `dashboard/tasks.py::send_issue_status_notifications` pour le
    déclenchement (scan des `IssueStatusStory.email_notified=False`, mobile comme web)."""
    titles = {
        'opened': _('COSO GRM - Issue opened'), 
        'investigation': _('COSO GRM - Issue investigation update'),
        'resolved': _('COSO GRM - Issue resolved'),
        'rejected': _('COSO GRM - Issue rejected'),
    }
    title = titles[kind]
    try:
        return send_email(
            f"{title} - {issue['tracking_code']} | {issue['internal_code']}",
            "mail/send/comment",
            {
                "datas": {
                    _("Title"): title,
                    _("Code"): issue['internal_code'],
                    _("Category"): issue['category']['name'],
                    _("Description"): "***" if "b'" in issue['description'] else issue['description'],
                    _("Status"): issue['status']['name'],
                    _("Level"): issue['escalation_administrativelevels'][0]['escalate_to']['administrative_level'] \
                        if 'escalation_administrativelevels' in issue and issue['escalation_administrativelevels'] else \
                            issue['category']['administrative_level'],
                    _("Comment"): story_comment or '-',
                },
                "user": {
                    _("Reporter"): issue['reporter']['name'] if issue.get('reporter') else '-',
                    _("Assigned to"): issue['assignee']['name'] if issue.get('assignee') else '-',
                },
                "url": f"{settings.GRM_URL_BASE}/grm/issue-detail/{issue['auto_increment_id']}/",
                'current_year': datetime.now().year,
            },
            _safeguard_specialist_emails(),
            cc=_team_email_cc() + _citizen_email_cc(issue) + _village_actors_email_cc(issue)
        )
    except:
        return None


def get_adminstrative_level_by_name(ad_name, canton_str: str):
    try:
        return mis_objects_call.get_object(AdministrativeLevel, name=ad_name, type="Village")
    except AdministrativeLevel.DoesNotExist as exc:
        try:
            return mis_objects_call.get_object(AdministrativeLevel, 
                name=strip_accents(ad_name), type="Village", parent__name=canton_str
            )
        except AdministrativeLevel.DoesNotExist as exc:
            try:
                return mis_objects_call.get_object(AdministrativeLevel, name=ad_name.replace(" ", ""), type="Village", parent__name=canton_str)
            except AdministrativeLevel.DoesNotExist as exc:
                try:
                    return mis_objects_call.get_object(AdministrativeLevel, 
                        name=strip_accents(ad_name.replace(" ", "")), type="Village", parent__name=canton_str
                    )
                except AdministrativeLevel.DoesNotExist as exc:
                    try:
                        return mis_objects_call.get_object(AdministrativeLevel, 
                            name=strip_accents(ad_name.replace("-", " ")), type="Village", parent__name=canton_str
                        )
                    except AdministrativeLevel.DoesNotExist as exc:
                        try:
                            return mis_objects_call.get_object(AdministrativeLevel, 
                                name=strip_accents(ad_name.replace(" ", "-")), type="Village", parent__name=canton_str
                            )
                        except AdministrativeLevel.DoesNotExist as exc:
                            try:
                                return mis_objects_call.get_object(AdministrativeLevel, 
                                    name=strip_accents(ad_name.replace(" ", "-")), type="Village", parent__name=canton_str
                                )
                            except AdministrativeLevel.DoesNotExist as exc:
                                return None
                            except AdministrativeLevel.MultipleObjectsReturned as exc:
                                return None
                        except AdministrativeLevel.MultipleObjectsReturned as exc:
                            return None
                    except AdministrativeLevel.MultipleObjectsReturned as exc:
                        return None
                
                except AdministrativeLevel.MultipleObjectsReturned as exc:
                    return None

            except AdministrativeLevel.MultipleObjectsReturned as exc:
                return None

        except AdministrativeLevel.MultipleObjectsReturned as exc:
            return None

    except AdministrativeLevel.MultipleObjectsReturned as exc:
        return None
    


def filter_adminstrative_level_by_name(ad_name, canton_str: str):
    _filters = None
    try:
        _filters = mis_objects_call.filter_objects(AdministrativeLevel, name=ad_name, type="Village")
    except AdministrativeLevel.DoesNotExist as exc:
        try:
            _filters = mis_objects_call.filter_objects(AdministrativeLevel, 
                name=strip_accents(ad_name), type="Village"
            )
        except AdministrativeLevel.DoesNotExist as exc:
            try:
                _filters = mis_objects_call.filter_objects(AdministrativeLevel, name=ad_name.replace(" ", ""), type="Village")
            except AdministrativeLevel.DoesNotExist as exc:
                try:
                    _filters = mis_objects_call.filter_objects(AdministrativeLevel, 
                        name=strip_accents(ad_name.replace(" ", "")), type="Village"
                    )
                except AdministrativeLevel.DoesNotExist as exc:
                    try:
                        _filters = mis_objects_call.filter_objects(AdministrativeLevel, 
                            name=strip_accents(ad_name.replace("-", " ")), type="Village"
                        )
                    except AdministrativeLevel.DoesNotExist as exc:
                        try:
                            _filters = mis_objects_call.filter_objects(AdministrativeLevel, 
                                name=strip_accents(ad_name.replace(" ", "-")), type="Village"
                            )
                        except AdministrativeLevel.DoesNotExist as exc:
                            try:
                                _filters = mis_objects_call.filter_objects(AdministrativeLevel, 
                                    name=strip_accents(ad_name.replace(" ", "-")), type="Village"
                                )
                            except AdministrativeLevel.DoesNotExist as exc:
                                _filters = None
                            except AdministrativeLevel.MultipleObjectsReturned as exc:
                                _filters = None
                        except AdministrativeLevel.MultipleObjectsReturned as exc:
                            _filters = None
                    except AdministrativeLevel.MultipleObjectsReturned as exc:
                        _filters = None
                
                except AdministrativeLevel.MultipleObjectsReturned as exc:
                    _filters = None

            except AdministrativeLevel.MultipleObjectsReturned as exc:
                _filters = None

        except AdministrativeLevel.MultipleObjectsReturned as exc:
            _filters = None

    except AdministrativeLevel.MultipleObjectsReturned as exc:
        _filters = None

    if _filters and _filters.count() > 1:
        for obj in _filters:
            if obj.parent and obj.parent.name == canton_str:
                return obj
    elif _filters:
        return _filters.first()
    
    return None




def _excel_cell(value):
    """Valeur d'une cellule Excel : openpyxl refuse les UUID, les datetimes avec fuseau et les
    caractères de contrôle (IllegalCharacterError) — présents dans des descriptions saisies sur le
    mobile ou reprises de CouchDB."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value, timezone.utc).replace(tzinfo=None)
        return value
    return ILLEGAL_CHARACTERS_RE.sub('', str(value))


def export_issues(request):
    """Export Excel (bouton « Télécharger toute la base de données ») des issues visibles par
    l'utilisateur, avec les filtres de la page : mêmes règles que le tableau
    (`build_issue_queryset`) et mêmes colonnes que l'ancien export CouchDB (document legacy
    `issue_to_legacy_dict` aplati : `category_name`, `comments_0_comment`...).

    Retourne le contenu du fichier .xlsx (bytes), envoyé directement dans la réponse : pas de
    fichier sur le disque de l'instance (non partagé entre instances EB)."""
    from dashboard.grm.serializers import issue_to_legacy_dict

    queryset, _ = build_issue_queryset(request)

    def append_data_to_dict(flat_doc: dict, dict_item: tuple):
        if type(dict_item[1]) in (dict, list):
            if type(dict_item[1]) == dict:
                for k, v in dict_item[1].items():
                    append_data_to_dict(flat_doc, (f"{dict_item[0]}_{k}", v))
            else:
                for i in range(len(dict_item[1])):
                    append_data_to_dict(flat_doc, (f"{dict_item[0]}_{i}", dict_item[1][i]))
        else:
            flat_doc[dict_item[0]] = _excel_cell(dict_item[1])

    # Par paquets de 500, chacun chargé avec son prefetch (≈ 10 requêtes par paquet, pas par
    # issue). Pas `queryset.iterator()` : avant Django 4.1, il ignore `prefetch_related`.
    data = []
    chunk_size = 500
    pks = list(queryset.values_list('pk', flat=True))
    for start in range(0, len(pks), chunk_size):
        for issue in queryset.filter(pk__in=pks[start:start + chunk_size]):
            flat_doc = {}
            for k, v in issue_to_legacy_dict(issue, prefetched=True).items():
                append_data_to_dict(flat_doc, (k, v))
            data.append(flat_doc)

    buffer = BytesIO()
    pd.DataFrame(data).to_excel(buffer, sheet_name='Plaintes', index=False)
    return buffer.getvalue()
