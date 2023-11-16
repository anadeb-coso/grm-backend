from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.views import generic
from django.contrib.auth.decorators import login_required
from dashboard.mixins import AJAXRequestMixin, PageMixin
from django.utils.translation import gettext_lazy as _
from django.core.paginator import Paginator
from django.db.models import Q
from django.core.exceptions import PermissionDenied
from django.template.loader import get_template
from django.http import HttpResponse
from datetime import datetime
from django.conf import settings
import pandas as pd
import random

from grm.my_librairies.convert_file_to_dict import (
    conversion_file_xlsx_to_dict, conversion_file_csv_to_dict, get_excel_sheets_names
    )
from grm.my_librairies.functions import strip_accents
from grm.call_objects_from_other_db import mis_objects_call
from dashboard.grm.functions import filter_adminstrative_level_by_name
from grm.utils import get_auto_increment_id
from client import get_db
from administrativelevels.models import AdministrativeLevel


COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE

def get_value(elt):
    return elt if not pd.isna(elt) else None

class SaveIssuesByFileView(PageMixin, LoginRequiredMixin, generic.TemplateView):
 

    def post(self, request, *args, **kwargs):
        
        file = request.FILES.get('file')
        datas_file = []
        if file:
            name = get_excel_sheets_names(file)[0]
            
            try:
                datas_file = conversion_file_xlsx_to_dict(file, name)
            except:
                try:
                    datas_file = conversion_file_csv_to_dict(file, name)
                except:
                    pass
        
        issues_found = []
        villages_unfound = []
        if datas_file:
            count = 0
            count_issues = 0
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
                last_level= (last_level if last_level else '').strip().title()
                try:
                    _issue = grm_db.get_query_result({
                        "description": resume_issue,
                        "type": 'issue',
                        "research_result": status_decription,
                        "administrative_region.name": village
                    })[0][0]
                except Exception:
                    _issue = None

                if not _issue:
                    if category:
                        try:
                            category_by_space = category.split(' ')[1].strip()
                            if category_by_space:
                                if ':' in category_by_space:
                                    category_by_space = category_by_ie.split(':')[0]
                                
                                if category_by_space.isdigit():
                                    category_id = int(category_by_space)
                        except:
                            pass

                        if category_id == 0:
                            try:
                                category_by_ie = category.split('ie')[1].strip()
                                if category_by_ie:
                                    if ':' in category_by_ie:
                                        category_by_ie = category_by_ie.split(':')[0]
                                    
                                    if category_by_ie.isdigit():
                                        category_id = int(category_by_ie)
                            except:
                                pass
                    
                    if category_id != 0 and village:
        
                        village_obj = filter_adminstrative_level_by_name(village, canton)
                        if village_obj:
                            escalation_administrativelevels = []
                            if last_level in ("Canton", "Prefecture", "Region", "Pays"):
                                escalation_administrativelevels.insert(0,
                                    {
                                        "escalate_to": {
                                            "administrative_id": str(village_obj.parent.id),
                                            "name": village_obj.parent.name,
                                            "administrative_level": "Canton"
                                        },
                                        "comment": f"{village_obj.name} à {village_obj.parent.name} (Canton)",
                                        "due_at": reception_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                                    }
                                )
                            if last_level in ("Prefecture", "Pays"):
                                escalation_administrativelevels.insert(0,
                                    {
                                        "escalate_to": {
                                            "administrative_id": str(village_obj.parent.parent.parent.id),
                                            "name": village_obj.parent.parent.parent.name,
                                            "administrative_level": "Prefecture"
                                        },
                                        "comment": f"{village_obj.parent.name} à {village_obj.parent.parent.parent.name} (Prefecture)",
                                        "due_at": reception_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                                    }
                                )
                            if last_level in ("Region", "Pays"):
                                escalation_administrativelevels.insert(0,
                                    {
                                        "escalate_to": {
                                            "administrative_id": str(village_obj.parent.parent.parent.parent.id),
                                            "name": village_obj.parent.parent.parent.parent.name,
                                            "administrative_level": "Region"
                                        },
                                        "comment": f"{village_obj.parent.name} à {village_obj.parent.parent.parent.parent.name} (Region)",
                                        "due_at": reception_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                                    }
                                )
                            if last_level == "Pays":
                                escalation_administrativelevels.insert(0,
                                    {
                                        "escalate_to": {
                                            "administrative_id": "1",
                                            "name": "TOGO",
                                            "administrative_level": "Country"
                                        },
                                        "comment": f"{village_obj.parent.parent.parent.parent.name} à TOGO (Pays)",
                                        "due_at": reception_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                                    }
                                )
                            

                            grm_db = get_db(COUCHDB_GRM_DATABASE)
                            auto_increment_id = get_auto_increment_id(grm_db)
                            
                            
                            try:
                                doc_category = grm_db.get_query_result({
                                    "id": category_id,
                                    "type": 'issue_category'
                                })[0][0]
                                department_id = doc_category['assigned_department']['id']
                            except Exception:
                                doc_category = None
                            
                            if doc_category:
                                assigned_department = doc_category['assigned_department'][
                                    'administrative_level'] if 'administrative_level' in doc_category['assigned_department'] else None
                                
                                sample_words = ["Tree", "Cat", "Dog", "Car", "House"]

                                issue = {
                                    "tracking_code": f'{random.choice(sample_words)}{random.choice(range(1, 1000))}',
                                    "auto_increment_id": auto_increment_id,
                                    "description": resume_issue,
                                    "attachments": [],
                                    "status": {
                                        "name": "Résolue",
                                        "id": 3
                                    } if resolve_date else {
                                        "name": "En cours de traitement",
                                        "id": 2
                                    },
                                    "confirmed": True,
                                    "assignee": {
                                        "id": 162,
                                        "name": "Fousséni KEGBAO"
                                    },
                                    "reporter": {
                                        "id": 162,
                                        "name": "Fousséni KEGBAO"
                                    },
                                    "citizen_age_group": None,
                                    "citizen": "",
                                    "contact_medium": "anonymous",
                                    "citizen_type": None,
                                    "citizen_group_1": None,
                                    "citizen_group_2": None,
                                    "citizen_or_group": None,
                                    "location_info": {
                                        "issue_location": {
                                        "administrative_id": str(village_obj.id),
                                        "name": village_obj.name
                                        },
                                        "location_description": None
                                    },
                                    "administrative_region": {
                                        "administrative_id": str(village_obj.id),
                                        "name": village_obj.name
                                    },
                                    "structure_in_charge": {
                                        "name": "Comité de gestion de plaintes",
                                        "phone": "",
                                        "email": ""
                                    },
                                    "category": {
                                                "id": doc_category['id'],
                                                "name": doc_category['name'],
                                                "confidentiality_level": doc_category['confidentiality_level'],
                                                "assigned_department": department_id,
                                                "administrative_level": assigned_department,
                                            },
                                    "issue_type": {
                                        "id": 1,
                                        "name": "Plainte"
                                    },
                                    "created_date": reception_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                                    "resolution_days": 0,
                                    "resolution_date": "",
                                    "reject_date": "",
                                    "intake_date": reception_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                                    "issue_date": reception_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                                    "ongoing_issue": False,
                                    "event_recurrence": False,
                                    "comments": [
                                        {
                                        "id": 162,
                                        "name": "Fousséni KEGBAO",
                                        "comment": "La plainte a été résolue",
                                        "due_at": reception_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                                        },
                                        {
                                        "id": 162,
                                        "name": "Fousséni KEGBAO",
                                        "issue_status": "Plainte résolue",
                                    "comment": "Resolué",
                                        "due_at": reception_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                                        }
                                    ],
                                    "contact_information": None,
                                    "type": "issue",
                                    "source": "web",
                                    "publish": True,
                                    "notification_send": True,
                                    "issue_status_stories": [
                                    ],
                                    "reasons": [
                                        {
                                        "user_name": "Fousséni KEGBAO",
                                        "user_id": 162,
                                        "comment": investigate,
                                        "due_at": resolve_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                                        "id": resolve_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                                        "type": "comment",
                                        "comment_id": resolve_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                                        },
                                        {
                                        "user_name": "Fousséni KEGBAO",
                                        "user_id": 162,
                                        "comment": status_decription,
                                        "due_at": resolve_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                                        "id": resolve_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                                        "type": "comment",
                                        "comment_id": resolve_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                                        }
                                    ] if resolve_date else [
                                        {
                                        "user_name": "Fousséni KEGBAO",
                                        "user_id": 162,
                                        "comment": investigate,
                                        "due_at": reception_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                                        "id": reception_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                                        "type": "comment",
                                        "comment_id": reception_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                                        }
                                    ],
                                    "research_result": status_decription,
                                    "resolution_files": [
                                    ]
                                }
                                if escalation_administrativelevels:
                                    issue['escalation_administrativelevels'] = escalation_administrativelevels
                                grm_db.create_document(issue)
                                count_issues += 1
                        else:
                            if village not in villages_unfound:
                                villages_unfound.append(village)
                else:
                    issues_found.append({
                        "description": resume_issue,
                        "type": 'issue',
                        "research_result": status_decription,
                        "administrative_region.name": village
                    })

                count += 1
            
            print("issues_found")
            print(issues_found)
            print("issues_found")
            print()

            print("villages_unfound")
            print(villages_unfound)
            print("villages_unfound")
            print()

            print(count_issues)
            print(len(issues_found))
        return HttpResponseRedirect(reverse('dashboard:grm:review_issues'))