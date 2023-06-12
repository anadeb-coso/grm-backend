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
        "name": user.get_full_name(),
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
        "administrative_region": "1",
        "department": 1,
        "unique_region": 0,
        "village_secretary": 1
    }

    if updated:
        for k, v in doc_user.items():
            doc_user_update[k] = v
        doc_user_update.save()
    else:
        eadl_db.create_document(doc_user)

def delete_adl_user_adl(user):
    eadl_db = get_db()
    eadl_db[eadl_db.get_query_result({"type": "adl", "representative.id": user.id})[0][0]["_id"]].delete()