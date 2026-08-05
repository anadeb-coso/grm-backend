from datetime import datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.http import Http404
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from authentication.serializers import _facilitator_to_legacy_dict
from issue.models import Adl, Issue, IssueCategory, IssueStatus
from .permissions import HasGrmServiceKey
from .serializers import IssueCategoryServiceSerializer, IssueServiceSerializer, IssueStatusServiceSerializer

User = get_user_model()


class AdlByEmailView(APIView):
    """Remplace la requête Mango CouchDB `eadls` `{"representative.email": email}` utilisée par
    CDD (usermanager/*) et MIS (assignments/functions.py::get_stabilized_administrativelevels_of_facilitators_by_project_id).
    Renvoie la forme legacy du document `eadls` (authentication/serializers.py::_facilitator_to_legacy_dict),
    déjà consommée telle quelle par le code CDD/MIS existant (`doc['administrative_regions']`,
    `doc['representative']['email']`, etc.)."""
    permission_classes = [HasGrmServiceKey]

    def get(self, request):
        email = request.GET.get('email')
        emails = request.GET.getlist('emails', [])

        if email and not emails:
            user = User.objects.filter(email=email, is_active=True).first()
            if not user or not Adl.objects.filter(representative=user, is_deleted=False).exists():
                raise Http404
            return Response(_facilitator_to_legacy_dict(user))
        
        if email:
            emails.append(email)
        
        users = User.objects.filter(email__in=emails, is_active=True)
        if not users or not Adl.objects.filter(representative__in=users, is_deleted=False).exists():
            raise Http404
        
        return Response([_facilitator_to_legacy_dict(user) for user in users])


class AdlByVillageView(APIView):
    """Remplace la vue CouchDB `eadls` `_design/adl_village_filter/by_village_id` utilisée par
    MIS (administrativelevels/models.py::AdministrativeLevel.get_facilitator)."""
    permission_classes = [HasGrmServiceKey]

    def get(self, request):
        village_id = request.GET.get('village_id')
        village_ids = request.GET.getlist('village_ids', [])
        if village_id and not str(village_id).isdigit():
            return Response({'detail': 'village_id must be numeric'}, status=400)
        
        
        if village_id and str(village_id).isdigit():
            village_ids.append(str(village_id))

        village_ids = list(set([str(v_id) for v_id in village_ids if str(v_id).isdigit()]))
        
        query = Q()
        for i in village_ids:
            query |= Q(administrative_region_ids__contains=[i])
            query |= Q(smallest_administrative_level_ids__contains=[i])
            # query |= Q(additional_administrative_region_ids__contains=[i])
            # query |= Q(additional_smallest_administrative_level_ids__contains=[i])

        adls = Adl.objects.select_related('representative').filter(query).filter(
            is_deleted=False, representative__isnull=False,
        )

        return Response([_facilitator_to_legacy_dict(adl.representative) for adl in adls])

class VillagesWithAdlsView(APIView):
    permission_classes = [HasGrmServiceKey]

    def get(self, request):
        village_id = request.GET.get('village_id')
        village_ids = request.GET.getlist('village_ids', [])
        if village_id and not str(village_id).isdigit():
            return Response({'detail': 'village_id must be numeric'}, status=400)


        if village_id and str(village_id).isdigit():
            village_ids.append(str(village_id))

        village_ids = list(set([str(v_id) for v_id in village_ids if str(v_id).isdigit()]))

        query = Q()
        for i in village_ids:
            query |= Q(administrative_region_ids__contains=[i])
            query |= Q(smallest_administrative_level_ids__contains=[i])

        adls = Adl.objects.select_related('representative').filter(query).filter(
            is_deleted=False, representative__isnull=False,
        )

        village_ids_set = set(village_ids)
        result = {village_id: [] for village_id in village_ids}
        for adl in adls:
            adl_village_ids = set(adl.administrative_region_ids or []) | set(adl.smallest_administrative_level_ids or [])
            matched_village_ids = village_ids_set & adl_village_ids
            if not matched_village_ids:
                continue
            facilitator = _facilitator_to_legacy_dict(adl.representative)
            for village_id in matched_village_ids:
                result[village_id].append(facilitator)

        return Response(result)

class AdlListView(ListAPIView):
    """Liste complète des facilitateurs (remplace un `all_docs`/`get_query_result({"type":"adl"})`
    CouchDB `eadls` sans filtre, utilisé par les écrans d'export/statistiques CDD qui parcourent
    tous les documents). Pas de pagination configurée sur ce projet (cohérent avec le reste de
    l'API) : renvoie la liste complète."""
    permission_classes = [HasGrmServiceKey]
    pagination_class = None

    def get_queryset(self):
        return Adl.objects.select_related('representative').filter(
            is_deleted=False, representative__isnull=False,
        ).order_by('name')

    def list(self, request, *args, **kwargs):
        return Response([_facilitator_to_legacy_dict(adl.representative) for adl in self.get_queryset()])


class SetUserPasswordView(APIView):
    """Remplace la synchronisation de mot de passe CDD -> CouchDB `eadls`/MySQL legacy `grm`
    (usermanager/views_forget_password.py, usermanager/views_change_password.py) : CDD pousse ici
    le nouveau mot de passe en clair (même niveau de confiance que le secret partagé déjà utilisé
    pour update-user-adls sur CDD) pour garder les comptes GRM/CDD synchronisés."""
    permission_classes = [HasGrmServiceKey]

    def post(self, request):
        email = request.data.get('email')
        new_password = request.data.get('new_password')
        if not email or not new_password:
            return Response({'detail': 'email and new_password are required'}, status=400)
        user = User.objects.filter(email=email).first()
        if not user:
            raise Http404
        user.set_password(new_password)
        user.save(update_fields=['password'])
        return Response({'detail': 'password updated'})


class IssueCategoryListView(ListAPIView):
    """Remplace `get_issue_category_choices(grm_db)` (MIS administrativelevels/grm/functions.py)."""
    permission_classes = [HasGrmServiceKey]
    serializer_class = IssueCategoryServiceSerializer
    pagination_class = None
    queryset = IssueCategory.objects.filter(is_deleted=False).order_by('name')


class IssueStatusListView(ListAPIView):
    """Remplace `get_issue_status_choices(grm_db)` (MIS administrativelevels/grm/functions.py)."""
    permission_classes = [HasGrmServiceKey]
    serializer_class = IssueStatusServiceSerializer
    pagination_class = None
    queryset = IssueStatus.objects.filter(is_deleted=False).order_by('name')


class IssueListView(ListAPIView):
    """Remplace la recherche de plaintes CouchDB `grm` (MIS administrativelevels/grm/views.py::IssueListView).
    Appel de confiance (secret partagé) : pas de filtrage par périmètre utilisateur, MIS applique
    ses propres filtres via les query params ci-dessous (mêmes critères que l'ancien sélecteur Mango)."""
    permission_classes = [HasGrmServiceKey]
    serializer_class = IssueServiceSerializer

    def get_queryset(self):
        qs = Issue.objects.select_related(
            'status', 'category', 'assignee', 'reporter',
        ).filter(is_deleted=False)

        params = self.request.GET
        if params.get('confirmed') is not None:
            qs = qs.filter(confirmed=params.get('confirmed').lower() in ('1', 'true', 'yes'))
        if params.get('publish') is not None:
            qs = qs.filter(publish=params.get('publish').lower() in ('1', 'true', 'yes'))
        if params.get('auto_increment_id'):
            qs = qs.filter(auto_increment_id=params.get('auto_increment_id'))
        if params.get('status'):
            qs = qs.filter(status__legacy_id=params.get('status'))
        if params.get('category'):
            qs = qs.filter(category__legacy_id=params.get('category'))
        if params.get('assignee_email'):
            qs = qs.filter(assignee__email=params.get('assignee_email'))
        if params.get('reporter_email'):
            qs = qs.filter(reporter__email=params.get('reporter_email'))
        if params.get('administrative_region_id'):
            qs = qs.filter(administrative_region_id=params.get('administrative_region_id'))
        start_date = params.get('start_date')
        end_date = params.get('end_date')
        if start_date:
            qs = qs.filter(issue_date__gte=datetime.fromisoformat(start_date).replace(tzinfo=dt_timezone.utc))
        if end_date:
            qs = qs.filter(issue_date__lte=datetime.fromisoformat(end_date).replace(tzinfo=dt_timezone.utc))

        return qs.order_by('-issue_date')


class IssueStatsByAssigneeView(APIView):
    """Remplace la vue CouchDB `grm` `_design/issues/_view/by_assignee_stats`
    (MIS administrativelevels/grm/views.py::IssuesStatisticsView)."""
    permission_classes = [HasGrmServiceKey]

    def get(self, request):
        rows = (
            Issue.objects.filter(is_deleted=False, confirmed=True, assignee__isnull=False)
            .values('assignee__email', 'assignee__first_name', 'assignee__last_name')
            .annotate(total=Count('id'))
            .order_by('-total')
        )
        return Response([
            {
                'assignee_email': row['assignee__email'],
                'assignee_name': f"{row['assignee__first_name']} {row['assignee__last_name']}",
                'total': row['total'],
            }
            for row in rows
        ])
