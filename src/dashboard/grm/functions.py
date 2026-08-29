from django.utils.translation import gettext_lazy as _
from django.db.models import Q
from datetime import datetime, timedelta
from django.conf import settings
import pandas as pd
import os
from sys import platform

from grm.utils import datetime_str
from grm.my_librairies.mail.send_mail import send_email
from grm.constants import (
    SAFEGUARD_SPECIALIST_EMAILS, OTHER_SPECIALISTS_MAILS, ANADEB_EMAILS,
    OTHERS_EMAILS, ASSISTANTS_SAFEGUARD_SPECIALIST_EMAILS, COORDINATORS_EMAILS,
    REGIONAL_COORDINATORS_EMAILS
)
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
    assigned_to = get.get('assigned_to')
    category = get.get('category')
    issue_status = get.get('status')
    other = get.get('other')
    region = get.get('region')
    reported_by = get.get('reported_by')
    publish = get.get('publish')
    wave = get.get('wave')
    user = request.user

    queryset = Issue.objects.select_related(*ISSUE_SELECT_RELATED).prefetch_related(*ISSUE_PREFETCH_RELATED).filter(
        confirmed=True, is_deleted=False, auto_increment_id__isnull=False,
    )

    wave_object = None
    wave_administrative_ids = []
    if wave:
        wave_object = Wave.objects.filter(id=wave).first()
        if wave_object:
            wave_administrative_ids = wave_object.administrative_ids
            wave_administrative_ids_int = [int(elt) for elt in wave_administrative_ids if str(elt).isdigit()]
            queryset = queryset.filter(administrative_region_id__in=wave_administrative_ids_int)

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
        queryset = queryset.filter(publish=True)

    if start_date or wave_object:
        if start_date:
            start_date_dt = datetime.strptime(start_date, '%d/%m/%Y').date()
            if wave_object and wave_object.begin and start_date_dt < wave_object.begin:
                start_date_dt = wave_object.begin
        else:
            start_date_dt = wave_object.begin
        queryset = queryset.filter(intake_date__gte=start_date_dt)

    if end_date or (wave_object and wave_object.end):
        if end_date:
            end_date_dt = datetime.strptime(end_date, '%d/%m/%Y').date() + timedelta(days=1)
            if wave_object and wave_object.end and end_date_dt > wave_object.end + timedelta(days=1):
                end_date_dt = wave_object.end + timedelta(days=1)
        else:
            end_date_dt = wave_object.end + timedelta(days=1)
        queryset = queryset.filter(intake_date__lt=end_date_dt)

    if code:
        queryset = queryset.filter(
            Q(internal_code__icontains=code) | Q(tracking_code__icontains=code) | Q(description__icontains=code)
        )
    if assigned_to:
        queryset = queryset.filter(assignee_id=int(assigned_to))
    if category:
        queryset = queryset.filter(category__legacy_id=int(category))
    if issue_status:
        queryset = queryset.filter(status__legacy_id=int(issue_status))
    if other == 'Escalate':
        queryset = queryset.filter(escalation_reasons__isnull=False).distinct()
    if reported_by:
        queryset = queryset.filter(reporter_id=int(reported_by))
    if publish in ('True', 'False'):
        queryset = queryset.filter(publish=(publish == 'True'))

    if region:
        filter_regions = get_administrative_level_descendants_using_mis(None, region, [], user) + [str(region)]
        if wave_administrative_ids:
            filter_regions = list(set(filter_regions) & set(str(elt) for elt in wave_administrative_ids))
        filter_regions_int = [int(elt) for elt in filter_regions if str(elt).isdigit()]
        queryset = queryset.filter(administrative_region_id__in=filter_regions_int)

    queryset = queryset.order_by('-created_date')

    return queryset, wave_administrative_ids

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
            SAFEGUARD_SPECIALIST_EMAILS,
            cc= COORDINATORS_EMAILS + REGIONAL_COORDINATORS_EMAILS + ASSISTANTS_SAFEGUARD_SPECIALIST_EMAILS + OTHER_SPECIALISTS_MAILS + ANADEB_EMAILS + OTHERS_EMAILS + _citizen_email_cc(issue)
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
            SAFEGUARD_SPECIALIST_EMAILS,
            cc= COORDINATORS_EMAILS + REGIONAL_COORDINATORS_EMAILS + ASSISTANTS_SAFEGUARD_SPECIALIST_EMAILS + OTHER_SPECIALISTS_MAILS + ANADEB_EMAILS + OTHERS_EMAILS + _citizen_email_cc(issue)
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
            cc=REGIONAL_COORDINATORS_EMAILS + ASSISTANTS_SAFEGUARD_SPECIALIST_EMAILS + OTHERS_EMAILS + _citizen_email_cc(issue)
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
            SAFEGUARD_SPECIALIST_EMAILS,
            cc=COORDINATORS_EMAILS + REGIONAL_COORDINATORS_EMAILS + ASSISTANTS_SAFEGUARD_SPECIALIST_EMAILS + OTHER_SPECIALISTS_MAILS + ANADEB_EMAILS + OTHERS_EMAILS + _citizen_email_cc(issue)
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




def export_issues(request):
    grm_db = get_db(COUCHDB_GRM_DATABASE)
    adl_db = get_db(COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL)
    index = int(request.GET.get('index'))
    offset = int(request.GET.get('offset'))
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    code = request.GET.get('code')
    assigned_to = request.GET.get('assigned_to')
    category = request.GET.get('category')
    status = request.GET.get('status')
    other = request.GET.get('other')
    region = request.GET.get('region')
    reported_by = request.GET.get('reported_by')
    publish = request.GET.get('publish')
    wave = request.GET.get('wave')
    user = request.user

    selector = {
        "type": "issue",
        "confirmed": True,
        "auto_increment_id": {"$ne": ""},
        "created_date": {"$exists": True},
    }
    
    wave_administrative_ids = []
    if wave:
        wave_object = Wave.objects.filter(id=wave).first()
        if wave_object:
            wave_administrative_ids = wave_object.administrative_ids
            selector["administrative_region.administrative_id"] = {
                "$in": wave_administrative_ids + [int(elt) for elt in wave_administrative_ids if isinstance(elt, str) and elt.isdigit() and int(elt) not in wave_administrative_ids]
            }

    if user.groups.filter(name__in=["Admin", "ViewerOfAllIssues"]).exists():
        # selector = {
        #     "type": "issue",
        #     "confirmed": True,
        #     "auto_increment_id": {"$ne": ""},
        #     "created_date": {"$exists": True},
        # }
        pass
    else:
        # selector = {
        #     "type": "issue",
        #     "confirmed": True,
        #     "auto_increment_id": {"$ne": ""},
        #     "created_date": {"$exists": True},
        # }
        
        if hasattr(user, 'governmentworker') and user.governmentworker.administrative_id != "1":
            parent_ids = user.governmentworker.all_administrative_ids
            
            descendants = []
            for p_id in parent_ids:
                descendants += get_administrative_level_descendants_using_mis(adl_db, p_id, [], request.user)
            allowed_regions = descendants + parent_ids
            
            if wave_administrative_ids:
                allowed_regions = list(set(allowed_regions) & set(wave_administrative_ids))


            selector["$or"] = [
                {"assignee.id": user.id},
                {"$and": [
                    {"category.assigned_department": user.governmentworker.department},
                    {"administrative_region.administrative_id": {"$in": allowed_regions + [int(elt) for elt in allowed_regions if isinstance(elt, str) and elt.isdigit() and int(elt) not in allowed_regions]}},
                ]}
            ]
        else:
            # selector = {
            #     "type": "issue",
            #     "publish": True,
            #     "confirmed": True,
            #     "auto_increment_id": {"$ne": ""},
            # }
            selector["publish"] = True

    if start_date or wave_administrative_ids: #"2026-05-05T20:19:24.616Z"
        if start_date:
            start_date = datetime.strptime(start_date, '%d/%m/%Y').strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            if wave_administrative_ids:
                wave_begin_date = wave_object.begin.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                if start_date < wave_begin_date:
                    start_date = wave_begin_date
        elif wave_administrative_ids:
            start_date = wave_object.begin.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        selector["intake_date"] = {"$gte": start_date}
    if end_date or (wave_administrative_ids and wave_object.end):
        if end_date:
            end_date = datetime.strptime(end_date, '%d/%m/%Y').strftime('%Y-%m-%dT%23:59:59.999999Z') #(datetime.strptime(end_date, '%d/%m/%Y') + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            if wave_administrative_ids and end_date:
                wave_end_date = wave_object.end.strftime('%Y-%m-%dT%23:59:59.999999Z')
                if end_date > wave_end_date:
                    end_date = wave_end_date
        elif wave_administrative_ids and wave_object.end:
            end_date = wave_object.end.strftime('%Y-%m-%dT%23:59:59.999999Z')
            
        if "intake_date" not in selector:
            selector["intake_date"] = {"$lte": end_date}
        else:
            selector["intake_date"]["$lte"] = end_date


    if code:
        code_filter = {"$regex": f"(?i){code}"} #{"$regex": f"^{code}"}
        selector['$or'] = [{"internal_code": code_filter}, {"tracking_code": code_filter},
                            {"description": code_filter}]
    if assigned_to:
        selector["assignee.id"] = int(assigned_to)
    if category:
        selector["category.id"] = int(category)
        
    if status:
        selector["status.id"] = int(status)
    if other:
        if other == "Escalate":
            selector["escalation_reasons"] = {"$exists": True}
    if reported_by:
        selector["reporter.id"] = int(reported_by)
    if publish in ('True', 'False'):
        selector["publish"] = True if publish == 'True' else False

    if region:
        filter_regions = get_administrative_level_descendants_using_mis(adl_db, region, [], request.user) + [region]
        if wave_administrative_ids:
            filter_regions = list(set(filter_regions) & set(wave_administrative_ids))
        selector["administrative_region.administrative_id"] = {
            "$in": filter_regions + [int(elt) for elt in filter_regions if isinstance(elt, str) and elt.isdigit() and int(elt) not in filter_regions]
        }

    issues = grm_db.get_query_result(selector, sort=[{'created_date': 'desc'}])
    data = []

    def append_data_to_dict(flat_doc: dict, dict_item: tuple):
        if type(dict_item[1]) in (dict, list):
            if type(dict_item[1]) == dict:
                for k, v in dict_item[1].items():
                    append_data_to_dict(flat_doc, (f"{dict_item[0]}_{k}", v))
            else:
                for i in range(len(dict_item[1])):
                    append_data_to_dict(flat_doc, (f"{dict_item[0]}_{i}", dict_item[1][i]))
        else:
            flat_doc[dict_item[0]] = dict_item[1]

    for row in issues:
        # doc = row.get('doc', {})
        # flat_doc = {
        #     'ID': doc.get('_id', ''),
        #     'ID': doc.get('auto_increment_id', ''),
        #     'Code interne': doc.get('internal_code', ''),
        #     'Code de suivi': doc.get('tracking_code', ''),
        #     'Description': doc.get('description', ''),
        #     'Statut': doc.get('status', {}).get('name', ''),
        #     'Date de création': doc.get('created_date', ''),
        #     'Date de résolution': doc.get('resolution_date', ''),
        # }
        
        # # Concaténer les commentaires dans un champ
        # comments = doc.get('comments', [])
        # flat_doc['Commentaires'] = " | ".join([c.get('comment', '') for c in comments])
        
        # data.append(flat_doc)
        flat_doc = {}
        for k, v in row.items():
            append_data_to_dict(flat_doc, (k, v))

        data.append(flat_doc)

    df = pd.DataFrame(data)


    if not os.path.exists("media/grm"):
            os.makedirs("media/grm")
    file_path = f'grm/complaints_{str(datetime.today().replace(microsecond=0)).replace("-", "").replace(":", "").replace(" ", "_")}.xlsx'

    df = df.to_excel("media/"+file_path, sheet_name='Plaintes', index=False)

    # with pd.ExcelWriter("media/"+file_path) as writer:
    #     df.to_excel(writer, sheet_name='Planning Situation', index=False)
        
        # for k, v in datas_dict_planning.items():
        #     if k != 'Précédentes':
        #         pd.DataFrame(
        #             v
        #         ).to_excel(writer, sheet_name=k, index=False)
        
    if platform == "win32":
        # windows
        return file_path.replace("/", "\\\\")
    else:
        return file_path