import os
import zlib
from django.conf import settings
from django.utils import timezone

import shortuuid as uuid

from authentication.functions import send_code_by_mail, update_user_adl_on_cdd_app
from administrativelevels.functions import get_cascade_administrative_levels_by_administrative_level_id
from administrativelevels.serializers import AdministrativeLevelSerializer


def photo_path(instance, filename):
    filename, file_extension = os.path.splitext(filename)
    filename = '{}{}'.format(uuid.uuid(), file_extension)
    return 'photos/{}'.format(filename)


def get_validation_code(seed):
    return str(zlib.adler32(str(seed).encode('utf-8')))[:6]

def generate_administrative_regions_objects(ids, _id=None):
    try:
        administrative_regions = list(
            set(
                (ids if ids else list()) + \
                ([_id] if _id else [])
            )
        )
        # print(administrative_regions)
    except Exception as exc:
        administrative_regions = [_id] if _id else []
        
    cantons, villages = [], []
    for adm_region in administrative_regions:
        if adm_region not in (1, "1"):
            _cantons, _villages = get_cascade_administrative_levels_by_administrative_level_id(adm_region)
            cantons += _cantons
            villages += _villages
    
    cantons = set(list(cantons))
    villages = set(list(villages))
    
    administrative_regions_objects = []
    for canton in cantons:
        ad_ser = AdministrativeLevelSerializer(canton).data
        ad_ser["country"] = "1"
        ad_ser["commune"] = canton.parent_id
        ad_ser["prefecture"] = canton.parent.parent_id
        ad_ser["region"] = canton.parent.parent.parent_id
        ad_ser["villages"] = [
           AdministrativeLevelSerializer(village).data for village in villages if village.parent_id == canton.id
        ]
        administrative_regions_objects.append(ad_ser)

    return administrative_regions_objects, [v.id for v in villages]


def create_or_update_adl_user_adl(user, updated=False):
    """Tient à jour l'enregistrement `issue.Adl` Postgres rattaché à ce représentant (remplace
    l'ancien miroir écrit dans le document CouchDB `eadls` à chaque sauvegarde de `User` — l'Adl
    Postgres, alimenté par `migrate_eadls` et le dashboard, est désormais la source de vérité,
    donc aucune valeur n'est ré-écrasée si l'Adl existe déjà). `updated=False` signale un `User`
    tout juste créé : on envoie le code de validation par email, comme avant."""
    from issue.models import Adl

    if not updated:
        send_code_by_mail(user, get_validation_code(user.email))  # Send user account code on their Email

    Adl.objects.get_or_create(
        representative=user,
        defaults={
            'representative_name': user.get_full_name(),
        },
    )


def delete_adl_user_adl(user):
    from issue.models import Adl

    # `updated_at` doit être explicitement forcé : `QuerySet.update()` n'applique jamais `auto_now`
    # (contrairement à `Model.save()`) — sans ça, la suppression de l'Adl reste invisible au pull
    # (référentiel `adls`, lecture seule côté mobile, cf. sync/views.py::SYNC_READONLY_MODELS).
    Adl.objects.filter(representative=user).update(is_deleted=True, updated_at=timezone.now())


def set_user_government_worker_adl(government_worker):
    """Reporte le périmètre administratif du `GovernmentWorker` sur l'Adl Postgres correspondant,
    puis notifie l'application CDD externe (intégration indépendante de CouchDB, inchangée)."""
    from issue.models import Adl

    adl = Adl.objects.filter(representative=government_worker.user).first()
    if adl is None:
        return

    try:
        _, village_ids = generate_administrative_regions_objects(
            government_worker.administrative_ids, government_worker.administrative_id
        )
        _, additional_village_ids = generate_administrative_regions_objects(
            government_worker.additional_administrative_ids
        )

        adl.name = government_worker.administrative_level().type if government_worker.administrative_id else adl.name
        adl.location_name = government_worker.administrative_level().name if government_worker.administrative_id else adl.location_name
        # `GovernmentWorker.administrative_ids`/`additional_administrative_ids` sont nullables
        # (JSONField null=True), contrairement à `Adl.administrative_region_ids` (default=list,
        # non nullable) : normaliser None -> [] pour éviter une IntegrityError silencieuse au save.
        adl.administrative_region_ids = government_worker.administrative_ids or []
        adl.smallest_administrative_level_ids = [str(v_id) for v_id in village_ids]
        adl.additional_administrative_region_ids = government_worker.additional_administrative_ids or []
        adl.additional_smallest_administrative_level_ids = [str(v_id) for v_id in additional_village_ids]
        # `updated_at` explicitement listé : cf. delete_adl_user_adl() ci-dessus pour la raison
        # (sinon la réaffectation de périmètre administratif du facilitateur ne remonte jamais au
        # pull mobile).
        adl.save(update_fields=[
            'name', 'location_name', 'administrative_region_ids', 'additional_administrative_region_ids',
            'smallest_administrative_level_ids', 'additional_smallest_administrative_level_ids', 'updated_at',
        ])

        update_user_adl_on_cdd_app(
            government_worker.user.email, settings.GRM_SECRET_KEY_GENRATE, village_ids, additional_village_ids
        )
    except Exception as exc:
        print(government_worker.user.id)
        pass


def delete_user_government_worker_adl(government_worker):
    from issue.models import Adl

    # cf. delete_adl_user_adl() ci-dessus pour la raison du `updated_at` explicite.
    Adl.objects.filter(representative=government_worker.user).update(
        administrative_region_ids=[], additional_administrative_region_ids=[],
        smallest_administrative_level_ids=[], additional_smallest_administrative_level_ids=[],
        updated_at=timezone.now(),
    )