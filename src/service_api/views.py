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


class AdlUpdateLocalitiesView(APIView):
    """Pendant de `update-user-adls/` (GRM -> CDD) dans l'autre sens : CDD pousse ici les localités
    d'un facilitateur modifiées depuis sa page « Localités ». Même enregistrement que le formulaire
    `edit-user-government-worker/<id>/` : `GovernmentWorker` (niveau principal, niveaux choisis et
    localités additionnelles, villages étendus à leur CVD) ; le signal `post_save` met ensuite à jour
    l'`Adl` et renvoie les villages calculés à CDD."""
    permission_classes = [HasGrmServiceKey]

    def post(self, request):
        from authentication.models import GovernmentWorker
        from authentication.utils import expand_administrative_ids_with_cvd

        email = (request.data.get('email') or '').strip()
        if not email:
            return Response({'detail': 'email is required'}, status=400)
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            raise Http404

        administrative_id = request.data.get('administrative_id')
        administrative_id = str(administrative_id) if administrative_id not in (None, '') else None
        administrative_ids = [str(i) for i in (request.data.get('administrative_ids') or [])]
        additional_administrative_ids = [str(i) for i in (request.data.get('additional_administrative_ids') or [])]

        governmentworker = GovernmentWorker.objects.filter(user=user).first()
        if governmentworker is None:
            governmentworker = GovernmentWorker(user=user, department=1)

        governmentworker.administrative_id = administrative_id
        if administrative_id == "1":  # TOGO : même règle qu'à la création du profil
            governmentworker.administrative_ids = list()
            governmentworker.additional_administrative_ids = list()
        else:
            governmentworker.administrative_ids = expand_administrative_ids_with_cvd(administrative_ids, administrative_id)
            governmentworker.additional_administrative_ids = expand_administrative_ids_with_cvd(additional_administrative_ids)
        governmentworker.save()

        return Response({
            'status': 'success',
            'adl': Adl.objects.filter(representative=user, is_deleted=False).exists(),
            'administrative_id': governmentworker.administrative_id,
            'administrative_ids': governmentworker.administrative_ids,
            'additional_administrative_ids': governmentworker.additional_administrative_ids,
        })


FACILITATOR_GROUPS = {
    'community_facilitator': 'CommunityFacilitator',
    'technical_facilitator': 'TechnicalFacilitator',
}


class FacilitatorAccountView(APIView):
    """Compte MGP d'un facilitateur créé dans le DCC (sens unique : le MGP ne crée jamais de facilitateur dans le
    DCC).

    `create: true` : crée le compte (e-mail, nom, téléphone, empreinte du mot de passe du DCC — un seul mot de
    passe pour les deux plateformes, pas de code d'activation —, groupe CommunityFacilitator/TechnicalFacilitator,
    profil d'agent et localités de stabilisation comme `adls/update-localities/`). Un compte de même e-mail
    existant est laissé tel quel (`status: exists`).
    `create: false` : reporte un nouvel e-mail, nom ou téléphone sur le compte trouvé par `previous_email` (404 s'il
    n'existe pas)."""
    permission_classes = [HasGrmServiceKey]

    def post(self, request):
        from django.contrib.auth.hashers import identify_hasher
        from django.contrib.auth.models import Group
        from django.db import transaction

        data = request.data
        email = (data.get('email') or '').strip()
        if not email:
            return Response({'detail': 'email is required'}, status=400)

        if not data.get('create'):
            previous = (data.get('previous_email') or email).strip()
            user = User.objects.filter(email__iexact=previous).first()
            if not user:
                raise Http404
            if User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
                return Response({'detail': 'email already used'}, status=409)
            user.email = email
            user.first_name = data.get('first_name') or user.first_name
            user.last_name = data.get('last_name') or user.last_name
            user.phone_number = data.get('phone') or user.phone_number
            user.save(update_fields=['email', 'first_name', 'last_name', 'phone_number'])
            # `representative_name` : copie du nom lue par la synchronisation mobile ; `updated_at` explicitement listé
            # (cf. authentication/utils.py::delete_adl_user_adl).
            for adl in Adl.objects.filter(representative=user):
                adl.representative_name = user.get_full_name()
                adl.save(update_fields=['representative_name', 'updated_at'])
            return Response({'status': 'updated', 'id': user.id})

        existing = User.objects.filter(email__iexact=email).first()
        if existing:
            return Response({'status': 'exists', 'id': existing.id})

        group_name = FACILITATOR_GROUPS.get(data.get('facilitator_type'))
        if not group_name:
            return Response({'detail': 'unknown facilitator_type'}, status=400)
        password_hash = data.get('password_hash') or ''
        try:
            identify_hasher(password_hash)
        except ValueError:
            return Response({'detail': 'invalid password_hash'}, status=400)

        with transaction.atomic():
            user = User(
                email=email, first_name=data.get('first_name') or '', last_name=data.get('last_name') or '',
                phone_number=data.get('phone') or '', is_active=bool(data.get('is_active', True)),
            )
            user.password = password_hash  # même mot de passe que dans le DCC
            user._skip_validation_code_mail = True  # identifiants déjà envoyés par le DCC
            user.save()
            user.groups.add(Group.objects.get_or_create(name=group_name)[0])

        self._save_government_worker(user, data)
        return Response({
            'status': 'created', 'id': user.id,
            'adl': Adl.objects.filter(representative=user, is_deleted=False).exists(),
        })

    @staticmethod
    def _save_government_worker(user, data):
        """Profil d'agent et localités : même enregistrement qu'`AdlUpdateLocalitiesView` (le signal `post_save`
        met à jour l'`Adl` et renvoie les villages calculés au DCC)."""
        from authentication.models import GovernmentWorker
        from authentication.utils import expand_administrative_ids_with_cvd

        administrative_id = data.get('administrative_id')
        administrative_id = str(administrative_id) if administrative_id not in (None, '') else None
        administrative_ids = [str(i) for i in (data.get('administrative_ids') or [])]
        additional_administrative_ids = [str(i) for i in (data.get('additional_administrative_ids') or [])]

        governmentworker = GovernmentWorker(user=user, department=1, administrative_id=administrative_id)
        if administrative_id == "1":
            governmentworker.administrative_ids = list()
            governmentworker.additional_administrative_ids = list()
        else:
            governmentworker.administrative_ids = expand_administrative_ids_with_cvd(administrative_ids, administrative_id) if administrative_id or administrative_ids else list()
            governmentworker.additional_administrative_ids = expand_administrative_ids_with_cvd(additional_administrative_ids)
        governmentworker.save()


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
        user = User.objects.filter(email=email).first() or User.objects.filter(email__iexact=email).first()
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
