from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from administrativelevels.models import AdministrativeLevel
from grm.utils import get_administrative_level_descendants_using_mis
from issue.models import Adl


class AdministrativeLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdministrativeLevel
        fields = ['id', 'name', 'type', 'parent', 'latitude', 'longitude']


class AdministrativeLevelsPagination(PageNumberPagination):
    page_size = 1000
    page_size_query_param = 'page_size'


def _collect_ancestor_ids(base_ids):
    """Marche la chaîne `parent` (village -> canton -> commune -> préfecture -> région) pour
    chaque id de base, et retourne l'ensemble des ids rencontrés (base + tous les ancêtres) —
    nécessaire pour que les formulaires de saisie côté mobile puissent afficher le nom de chaque
    niveau parent d'un village, pas seulement le village lui-même."""
    all_ids = {int(i) for i in base_ids if str(i).isdigit()}
    frontier = set(all_ids)
    while frontier:
        parent_ids = AdministrativeLevel.objects.filter(
            id__in=frontier, parent__isnull=False,
        ).values_list('parent_id', flat=True)
        frontier = set(parent_ids) - all_ids
        all_ids |= frontier
    return all_ids


class AdministrativeLevelsView(APIView):
    """Endpoint séparé et distinct du protocole `pull`/`push` habituel (CLAUDE.md §2.1/§4.7) :
    `AdministrativeLevel` vit dans la base MySQL `mis`, source de vérité externe sans suivi
    `updated_at` fiable pour du sync incrémental. Le mobile l'appelle à part
    (`syncAdministrativeLevels()`), moins fréquemment que `runSync()`.

    Le référentiel complet (plusieurs milliers de lignes) n'a pas besoin d'être stocké sur chaque
    appareil : seule la zone d'intervention de l'utilisateur (ses villages, plus leur chaîne de
    parents pour l'affichage canton/commune/préfecture/région) est utile. Un `GovernmentWorker`
    avec `administrative_id == "1"` (portée nationale) reste seul à recevoir le dump complet."""
    permission_classes = [IsAuthenticated]
    pagination_class = AdministrativeLevelsPagination

    def get(self, request):
        queryset = self._scoped_queryset(request.user)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        serializer = AdministrativeLevelSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @staticmethod
    def _scoped_queryset(user):
        government_worker = getattr(user, 'governmentworker', None)
        if government_worker and government_worker.administrative_id == "1":
            return AdministrativeLevel.objects.order_by('id')

        base_ids = set()
        adl = Adl.objects.filter(representative=user, is_deleted=False).first()
        if adl:
            base_ids.update(adl.smallest_administrative_level_ids or [])
            base_ids.update(adl.additional_smallest_administrative_level_ids or [])
        elif government_worker:
            for admin_id in (government_worker.all_administrative_ids or []):
                base_ids.add(admin_id)
                base_ids.update(get_administrative_level_descendants_using_mis(None, admin_id, [], user))

        if not base_ids:
            # Profil sans Adl ni GovernmentWorker (ne devrait pas arriver pour un utilisateur
            # authentifié du mobile) : comportement précédent (dump complet) conservé par
            # sécurité plutôt que de renvoyer un référentiel vide qui casserait les formulaires.
            return AdministrativeLevel.objects.order_by('id')

        all_ids = _collect_ancestor_ids(base_ids)
        return AdministrativeLevel.objects.filter(id__in=all_ids).order_by('id')
