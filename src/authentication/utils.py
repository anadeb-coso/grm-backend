import os
import zlib
from django.conf import settings

import shortuuid as uuid

from client import get_db
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
    eadl_db = get_db()
    doc_user_update = {}
    if updated:
        try:
            doc_user_update = eadl_db[eadl_db.get_query_result({"type": "adl", "representative.id": user.id})[0][0]["_id"]]
        except Exception as exc:
            updated = False
    else:
        send_code_by_mail(user, get_validation_code(user.email)) # Send user account code on their Email
    
    doc_user = {
        "type": "adl",
        "photo": doc_user_update['photo'] if doc_user_update else "https://via.placeholder.com/150",
        "location": {
            "lat": 0,
            "long": 0
        },
        "representative": {
            "id": user.id,
            "name": user.get_full_name(),
            "email": user.email,
            "phone": user.phone_number,
            "photo": doc_user_update['representative']['photo'] if doc_user_update else "https://via.placeholder.com/150",
            "is_active": user.is_active,
            "last_active": doc_user_update['representative']['last_active'] if doc_user_update else (user.last_login.strftime('%Y-%m-%dT%H:%M:%S.%fZ') if user and user.last_login else None),
            "password": user.password,
            "groups": [g.name for g in user.groups.all()]
        },
        "phases": [],
        "department": 1,
        "unique_region": 0,
        "village_secretary": 1
    }

    if not updated:
        doc_user['name'] = None
        doc_user['location_name'] = None
        doc_user['administrative_region'] = None
        doc_user['administrative_regions'] = []

    # if hasattr(user, 'governmentworker') and user.governmentworker.administrative_id:
    #     doc_user['name'] = user.governmentworker.administrative_level().type
    #     doc_user['location_name'] = user.governmentworker.administrative_level().name
    #     doc_user['administrative_region'] = user.governmentworker.administrative_id
    #     doc_user['administrative_regions'] = user.governmentworker.administrative_ids

    if updated:
        for k, v in doc_user.items():
            doc_user_update[k] = v
        doc_user_update.save()
    else:
        eadl_db.create_document(doc_user)

def delete_adl_user_adl(user):
    eadl_db = get_db()
    eadl_db[eadl_db.get_query_result({"type": "adl", "representative.id": user.id})[0][0]["_id"]].delete()


def set_user_government_worker_adl(government_worker):
    eadl_db = get_db()
    doc_user_update = {}
    try:
        doc_user_update = eadl_db[eadl_db.get_query_result({"type": "adl", "representative.id": government_worker.user.id})[0][0]["_id"]]
    
        _administrative_regions_objects = generate_administrative_regions_objects(government_worker.administrative_ids, government_worker.administrative_id)
        _additional_administrative_regions_objects = generate_administrative_regions_objects(government_worker.additional_administrative_ids)

        doc_user = {
            "name": government_worker.administrative_level().type,
            "location_name": government_worker.administrative_level().name,
            "administrative_region": government_worker.administrative_id,
            "administrative_regions": government_worker.administrative_ids,
            "administrative_regions_objects": _administrative_regions_objects[0],
            "additional_administrative_regions": government_worker.additional_administrative_ids,
            "additional_administrative_regions_objects": _additional_administrative_regions_objects[0]
        }

        for k, v in doc_user.items():
            doc_user_update[k] = v
        doc_user_update.save()

        update_user_adl_on_cdd_app(
            doc_user_update['representative']['email'], settings.GRM_SECRET_KEY_GENRATE,
            _administrative_regions_objects[1], _additional_administrative_regions_objects[1]
        )
    except Exception as exc:
        print(government_worker.user.id)
        pass
    
    

def delete_user_government_worker_adl(government_worker):
    eadl_db = get_db()
    doc_user_update = {}
    try:
        doc_user_update = eadl_db[eadl_db.get_query_result({"type": "adl", "representative.id": government_worker.user.id})[0][0]["_id"]]
        
        doc_user = {
            "administrative_region": None
        }

        for k, v in doc_user.items():
            doc_user_update[k] = v
        doc_user_update.save()
    except Exception as exc:
        print(government_worker.user.id)
        pass