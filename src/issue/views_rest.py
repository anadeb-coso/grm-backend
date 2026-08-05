from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from datetime import datetime, timedelta

from issue.serializers import SaveIssueDatasSerializer, CheckSyncIssuesSerializer
# Réutilise la traduction dict-legacy -> champs Postgres déjà écrite pour le dashboard web
# (dashboard/grm/serializers.py, cf. sa docstring) plutôt que de dupliquer la résolution de FK
# (status/category/issue_type/administrative_region/assignee/reporter) : ces vues REST reçoivent
# des payloads au même format CouchDB historique, envoyés par les installations mobiles
# pré-WatermelonDB encore en circulation.
from dashboard.grm.serializers import LegacyIssueDoc, translate_scalar_field, issue_to_legacy_dict
from dashboard.tasks import (
    check_issues, send_sms_message, escalate_issues, send_a_new_issue_notification,
    send_issue_status_notifications,
)
from authentication.api.auth.login import CheckUserSerializer
from grm.utils import get_administrative_level_descendants_using_mis
from grm.api.custom import CustomPagination
from grm.call_objects_from_other_db import mis_objects_call
from administrativelevels.models import AdministrativeLevel
from issue.models import Issue

ISSUE_SELECT_RELATED = ('status', 'category', 'age_group', 'issue_type')


def _create_issue_from_legacy_payload(issue_dict):
    """Crée une `Issue` Postgres à partir d'un payload au format legacy CouchDB (client mobile
    pré-WatermelonDB, cas `reporter.id == user_id` de `SaveIssueDatas` : le client a généré son
    propre `_id` côté PouchDB avant de pousser le document, conservé sur `legacy_couch_id` pour
    les mises à jour ultérieures)."""
    fields = {}
    for key, value in issue_dict.items():
        fields.update(translate_scalar_field(key, value))
    if not fields.get('internal_code') or not fields.get('status_id') or not fields.get('category_id') \
            or not fields.get('issue_type_id') or not fields.get('administrative_region_id'):
        return None
    fields.setdefault('auto_increment_id', issue_dict.get('auto_increment_id') or 0)
    fields['legacy_couch_id'] = issue_dict.get('_id')
    return Issue.objects.create(**fields)


class SaveIssueDatas(APIView):
    throttle_classes = ()
    # Auparavant ouvert (`permission_classes = ()`) : l'identité de l'appelant reposait uniquement
    # sur l'`email` fourni dans le corps de la requête (cf. SaveIssueDatasSerializer.validate),
    # sans aucune vérification — n'importe qui connaissant un email valide pouvait créer/modifier
    # des issues en son nom. Un token JWT valide est désormais obligatoire (grm-frontend adapté en
    # conséquence, cf. services/API.js::sync_datas, qui passe maintenant par le client authentifié
    # `api` au lieu d'un `fetch()` sans en-tête `Authorization`).
    permission_classes = (IsAuthenticated,)
    serializer_class = SaveIssueDatasSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        user_id = serializer.validated_data['user_id']
        has_error = False
        send_message = False

        for issue in serializer.validated_data['issues']:
            created = False
            if issue.get('reporter', {}).get('id') == user_id:
                target = Issue.objects.filter(legacy_couch_id=issue.get('_id')).first()
                if target is None:
                    try:
                        created = _create_issue_from_legacy_payload(issue) is not None
                    except Exception as exc:
                        print(exc)
                        has_error = True

            if not created and 'assignee' in issue and 'id' in issue['assignee'] and issue['assignee']['id'] == user_id:
                target = Issue.objects.select_related(*ISSUE_SELECT_RELATED).filter(
                    legacy_couch_id=issue.get('_id')
                ).first()
                if target is None:
                    has_error = True
                else:
                    try:
                        doc = LegacyIssueDoc(target)
                        for k, v in issue.items():
                            if k not in ('publish', 'notification_send', 'accepted_alert_sent', 'rejected_alert_sent', 'closed_alert_sent') and (v or v == False or v == 0):
                                if k in doc and doc[k] != v:
                                    send_message = True
                                doc[k] = v
                        doc.save()
                    except Exception as exc:
                        print(exc)
                        has_error = True

        check_issues()
        escalate_issues()
        send_sms_message()
        send_a_new_issue_notification()
        send_issue_status_notifications()

        return Response({
            'status': 'ok',
            'has_error': has_error,
            'message': _("During this update, we noticed that some data had been stored locally on your phone but were not automatically synced during yours recordings. We want to assure you that this issue has now been resolved. To ensure proper automatic syncing in the future, please clear the MGP app's storage data via your phone settings, or uninstall and reinstall the app.") if send_message else None
            }, status=status.HTTP_200_OK)


class CheckSyncIssues(APIView):
    throttle_classes = ()
    # Même raisonnement que SaveIssueDatas ci-dessus : token JWT désormais obligatoire.
    permission_classes = (IsAuthenticated,)
    serializer_class = CheckSyncIssuesSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        check_issues()
        escalate_issues()
        send_sms_message()
        send_a_new_issue_notification()
        send_issue_status_notifications()

        return Response({'status': 'ok'}, status=status.HTTP_200_OK)


class RestGetIssues(APIView):
    """Recherche paginée d'issues pour les clients REST pré-WatermelonDB encore en usage.
    Équivalent Postgres du sélecteur Mango CouchDB historique — même logique de visibilité par
    rôle que `dashboard/grm/functions.py::build_issue_queryset` (consolidée là pour le dashboard
    web ; non réutilisée telle quelle ici car les noms de paramètres de requête diffèrent :
    `assigned_to`/`reported_by`/`region_name`/`region_parent_name`, propres à cette API historique)."""
    throttle_classes = ()
    permission_classes = ()
    serializer_class = CheckUserSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')
        code = request.data.get('code')
        assigned_to = request.data.get('assigned_to')
        category = request.data.get('category')
        issue_status = request.data.get('status')
        other = request.data.get('other')
        region = request.data.get('region')
        region_name = request.data.get('region_name')
        region_parent_name = request.data.get('region_parent_name')
        reported_by = request.data.get('reported_by')
        publish = request.data.get('publish')
        user = request.user

        queryset = Issue.objects.select_related(*ISSUE_SELECT_RELATED).filter(
            confirmed=True, is_deleted=False, auto_increment_id__isnull=False,
        )

        if user.groups.filter(name__in=["Admin", "ViewerOfAllIssues"]).exists():
            pass
        elif hasattr(user, 'governmentworker') and user.governmentworker.administrative_id != "1":
            parent_ids = user.governmentworker.all_administrative_ids
            descendants = []
            for p_id in parent_ids:
                descendants += get_administrative_level_descendants_using_mis(None, p_id, [], user)
            allowed_regions = descendants + parent_ids
            allowed_regions_int = [int(elt) for elt in allowed_regions if str(elt).isdigit()]

            queryset = queryset.filter(
                Q(assignee_id=user.id) | Q(
                    category__assigned_department__id=user.governmentworker.department,
                    administrative_region_id__in=allowed_regions_int,
                )
            )
        else:
            queryset = queryset.filter(publish=True)

        if start_date:
            start_date_dt = datetime.strptime(start_date, '%d/%m/%Y')
            queryset = queryset.filter(intake_date__gte=start_date_dt)
        if end_date:
            end_date_dt = datetime.strptime(end_date, '%d/%m/%Y') + timedelta(days=1)
            queryset = queryset.filter(intake_date__lte=end_date_dt)
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

        if region or region_name:
            filter_regions = []
            if region_name:
                if region_parent_name:
                    adl_object = mis_objects_call.filter_objects(
                        AdministrativeLevel, name=region_name, parent__name=region_parent_name,
                    ).first()
                else:
                    adl_object = mis_objects_call.filter_objects(AdministrativeLevel, name=region_name).first()
                if adl_object:
                    filter_regions = get_administrative_level_descendants_using_mis(
                        None, adl_object.id, [], user,
                    ) + [adl_object.id]
            else:
                filter_regions = get_administrative_level_descendants_using_mis(None, region, [], user) + [region]

            filter_regions_int = [int(elt) for elt in filter_regions if str(elt).isdigit()]
            queryset = queryset.filter(administrative_region_id__in=filter_regions_int)

        queryset = queryset.order_by('-created_date')

        paginator = CustomPagination()
        page = paginator.paginate_queryset(list(queryset), request)
        paginated_data = [issue_to_legacy_dict(issue) for issue in page]

        return paginator.get_paginated_response(paginated_data)
