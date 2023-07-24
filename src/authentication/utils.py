import os
import zlib

import shortuuid as uuid

from client import get_db

def photo_path(instance, filename):
    filename, file_extension = os.path.splitext(filename)
    filename = '{}{}'.format(uuid.uuid(), file_extension)
    return 'photos/{}'.format(filename)


def get_validation_code(seed):
    return str(zlib.adler32(str(seed).encode('utf-8')))[:6]


def create_or_update_adl_user_adl(user, updated=False):
    eadl_db = get_db()
    doc_user_update = {}
    if updated:
        try:
            doc_user_update = eadl_db[eadl_db.get_query_result({"type": "adl", "representative.id": user.id})[0][0]["_id"]]
        except Exception as exc:
            updated = False
    
    doc_user = {
        "type": "adl",
        "name": None,
        "location_name": None,
        "photo": user.photo.url if user.photo else "https://via.placeholder.com/150",
        "location": {
            "lat": 0,
            "long": 0
        },
        "representative": {
            "id": user.id,
            "name": user.get_full_name(),
            "email": user.email,
            "phone": user.phone_number,
            "photo": user.photo.url if user.photo else "https://via.placeholder.com/150",
            "is_active": user.is_active,
            "last_active": None,
            "password": user.password
        },
        "phases": [],
        "administrative_region": None,
        "department": 1,
        "unique_region": 0,
        "village_secretary": 1
    }
    if hasattr(user, 'governmentworker') and user.governmentworker.administrative_id:
        doc_user['name'] = user.governmentworker.administrative_level().type
        doc_user['location_name'] = user.governmentworker.administrative_level().name
        doc_user['administrative_region'] = user.governmentworker.administrative_id

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
    except Exception as exc:
        pass
    print(government_worker.administrative_level())
    doc_user = {
        "name": government_worker.administrative_level().type,
        "location_name": government_worker.administrative_level().name,
        "administrative_region": government_worker.administrative_id,
    }

    for k, v in doc_user.items():
        doc_user_update[k] = v
    doc_user_update.save()

def delete_user_government_worker_adl(government_worker):
    eadl_db = get_db()
    doc_user_update = {}
    try:
        doc_user_update = eadl_db[eadl_db.get_query_result({"type": "adl", "representative.id": government_worker.user.id})[0][0]["_id"]]
    except Exception as exc:
        pass
    
    doc_user = {
        "administrative_region": None
    }

    for k, v in doc_user.items():
        doc_user_update[k] = v
    doc_user_update.save()