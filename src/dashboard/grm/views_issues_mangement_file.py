from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views import generic
from django.utils.translation import gettext_lazy as _
from django.http import HttpResponse
from django.utils import timezone
import pandas as pd
import random

from grm.my_librairies.convert_file_to_dict import (
    conversion_file_xlsx_to_dict, conversion_file_csv_to_dict, get_excel_sheets_names
    )
from grm.my_librairies.functions import strip_accents
from dashboard.mixins import PageMixin
from dashboard.grm.functions import filter_adminstrative_level_by_name, export_issues
from grm.utils import get_auto_increment_id_using_postgres
from issue.models import Comment, Issue, IssueCategory, IssueStatus, IssueType, Reason


def get_value(elt):
    return elt if not pd.isna(elt) else None


class SaveIssuesByFileView(PageMixin, LoginRequiredMixin, generic.TemplateView):
    """Import en masse d'issues historiques depuis un fichier Excel/CSV (outil ponctuel de
    reprise de données, colonnes françaises figées) — recensé lors de la migration du dashboard
    web. Réécrit contre les modèles Postgres `Issue`/`Comment`/`Reason` au lieu de
    `grm_db.create_document(...)`, en conservant le comportement d'origine (utilisateur/agent
    codé en dur "Fousséni KEGBAO", même heuristique de repérage de catégorie/village)."""

    def post(self, request, *args, **kwargs):

        file = request.FILES.get('file')
        datas_file = []
        if file:
            name = get_excel_sheets_names(file)[0]

            try:
                datas_file = conversion_file_xlsx_to_dict(file, name)
            except Exception:
                try:
                    datas_file = conversion_file_csv_to_dict(file, name)
                except Exception:
                    pass

        issues_found = []
        villages_unfound = []
        count_issues = 0
        if datas_file:
            count = 0
            long = len(list(datas_file.values())[0])
            while count < long:
                category_id = 0
                category = get_value(datas_file["Catégorie"][count])
                category = (category if category else '').strip()

                resume_issue = get_value(datas_file["DESCRIPTION SOMMAIRE DE PLAINTES RECUES"][count])
                reception_date = get_value(datas_file["DATE RECEPTION"][count])
                investigate = get_value(datas_file["TRAITEMENT (approche de solution)"][count])
                status_decription = get_value(datas_file["STATUT DE LA PLAINTE"][count])
                resolve_date = get_value(datas_file["DATE DE CLOTURE"][count])
                village = get_value(datas_file["Village"][count])
                village = (strip_accents(village.upper()) if village else '').strip()
                canton = get_value(datas_file["Canton"][count])
                canton = (strip_accents(canton.upper()) if canton else '').strip()
                last_level = get_value(datas_file["Niveau de gestion de la plainte"][count])
                last_level = (last_level if last_level else '').strip().title()

                _issue = Issue.objects.filter(
                    description=resume_issue, research_result=status_decription,
                    administrative_region_name=village,
                ).first()

                if not _issue:
                    if category:
                        try:
                            category_by_space = category.split(' ')[1].strip()
                            if category_by_space:
                                if ':' in category_by_space:
                                    category_by_space = category_by_space.split(':')[0]

                                if category_by_space.isdigit():
                                    category_id = int(category_by_space)
                        except Exception:
                            pass

                        if category_id == 0:
                            try:
                                category_by_ie = category.split('ie')[1].strip()
                                if category_by_ie:
                                    if ':' in category_by_ie:
                                        category_by_ie = category_by_ie.split(':')[0]

                                    if category_by_ie.isdigit():
                                        category_id = int(category_by_ie)
                            except Exception:
                                pass

                    if category_id != 0 and village:

                        village_obj = filter_adminstrative_level_by_name(village, canton)
                        if village_obj:
                            escalation_levels_to_create = []
                            reception_dt = timezone.make_aware(datetime_from_value(reception_date))
                            if last_level in ("Canton", "Prefecture", "Region", "Pays"):
                                escalation_levels_to_create.append({
                                    "administrative_id": village_obj.parent.id,
                                    "name": village_obj.parent.name,
                                    "administrative_level": "Canton",
                                    "due_at": reception_dt,
                                })
                            if last_level in ("Commune", "Prefecture", "Region", "Pays"):
                                escalation_levels_to_create.append({
                                    "administrative_id": village_obj.parent.parent.id,
                                    "name": village_obj.parent.parent.name,
                                    "administrative_level": "Commune",
                                    "due_at": reception_dt,
                                })
                            if last_level in ("Prefecture", "Pays"):
                                escalation_levels_to_create.append({
                                    "administrative_id": village_obj.parent.parent.parent.id,
                                    "name": village_obj.parent.parent.parent.name,
                                    "administrative_level": "Prefecture",
                                    "due_at": reception_dt,
                                })
                            if last_level in ("Region", "Pays"):
                                escalation_levels_to_create.append({
                                    "administrative_id": village_obj.parent.parent.parent.parent.id,
                                    "name": village_obj.parent.parent.parent.parent.name,
                                    "administrative_level": "Region",
                                    "due_at": reception_dt,
                                })
                            if last_level == "Pays":
                                escalation_levels_to_create.append({
                                    "administrative_id": 1,
                                    "name": "TOGO",
                                    "administrative_level": "Country",
                                    "due_at": reception_dt,
                                })

                            doc_category = IssueCategory.objects.filter(legacy_id=category_id).first()

                            if doc_category:
                                auto_increment_id = get_auto_increment_id_using_postgres()
                                sample_words = ["Tree", "Cat", "Dog", "Car", "House"]

                                doc_status = IssueStatus.objects.filter(
                                    legacy_id=3 if resolve_date else 2,
                                ).first()
                                doc_issue_type = IssueType.objects.filter(legacy_id=1).first()

                                issue = Issue.objects.create(
                                    tracking_code=f'{random.choice(sample_words)}{random.choice(range(1, 1000))}',
                                    auto_increment_id=auto_increment_id,
                                    internal_code=f'{doc_category.abbreviation}-{village_obj.id}-{auto_increment_id}',
                                    description=resume_issue,
                                    status=doc_status,
                                    confirmed=True,
                                    assignee_id=162,
                                    assignee_name="Fousséni KEGBAO",
                                    reporter_id=162,
                                    reporter_name="Fousséni KEGBAO",
                                    citizen="",
                                    contact_medium="anonymous",
                                    location_info={
                                        "issue_location": {
                                            "administrative_id": str(village_obj.id),
                                            "name": village_obj.name,
                                        },
                                        "location_description": None,
                                    },
                                    administrative_region_id=village_obj.id,
                                    administrative_region_name=village_obj.name,
                                    structure_in_charge={
                                        "name": "Comité de gestion de plaintes",
                                        "phone": "",
                                        "email": "",
                                    },
                                    category=doc_category,
                                    issue_type=doc_issue_type,
                                    created_date=reception_dt,
                                    resolution_days=0,
                                    intake_date=reception_dt,
                                    issue_date=reception_dt,
                                    ongoing_issue=False,
                                    event_recurrence=False,
                                    source="web",
                                    publish=True,
                                    notification_send=True,
                                    research_result=status_decription,
                                )

                                Comment.objects.create(
                                    issue=issue, author_id=162, author_name="Fousséni KEGBAO",
                                    comment="La plainte a été résolue", due_at=reception_dt,
                                )
                                Comment.objects.create(
                                    issue=issue, author_id=162, author_name="Fousséni KEGBAO",
                                    comment="Resolué", due_at=reception_dt,
                                )

                                if resolve_date:
                                    resolve_dt = timezone.make_aware(datetime_from_value(resolve_date))
                                    Reason.objects.create(
                                        issue=issue, subject='comment', user_id=162, user_name="Fousséni KEGBAO",
                                        comment=investigate, due_at=resolve_dt,
                                    )
                                    Reason.objects.create(
                                        issue=issue, subject='comment', user_id=162, user_name="Fousséni KEGBAO",
                                        comment=status_decription, due_at=resolve_dt,
                                    )
                                else:
                                    Reason.objects.create(
                                        issue=issue, subject='comment', user_id=162, user_name="Fousséni KEGBAO",
                                        comment=investigate, due_at=reception_dt,
                                    )

                                from issue.models import EscalationLevel
                                for level in escalation_levels_to_create:
                                    EscalationLevel.objects.create(issue=issue, **level)

                                count_issues += 1
                        else:
                            if village not in villages_unfound:
                                villages_unfound.append(village)
                else:
                    issues_found.append({
                        "description": resume_issue,
                        "research_result": status_decription,
                        "administrative_region_name": village,
                    })

                count += 1

        return HttpResponseRedirect(reverse('dashboard:grm:review_issues'))


def datetime_from_value(value):
    if hasattr(value, 'to_pydatetime'):
        return value.to_pydatetime()
    return value


class IssuesCSVView(PageMixin, LoginRequiredMixin, generic.TemplateView):
    """Class to download statistic under excel file"""

    template_name = 'grm/issue_list.html'
    context_object_name = 'Download'
    title = _("Download")
    active_level1 = 'issues'
    breadcrumb = [
        {
            'url': '',
            'title': title
        },
    ]

    def get(self, request, *args, **kwargs):

        file_path = export_issues(self.request)

        if not file_path:
            return redirect('dashboard:grm:review_issues')
        else:
            return HttpResponse(file_path)
