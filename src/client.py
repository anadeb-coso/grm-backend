from cloudant.client import CouchDB
from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage
import os
from datetime import datetime
import time

COUCHDB_DATABASE = settings.COUCHDB_DATABASE
COUCHDB_ATTACHMENT_DATABASE = settings.COUCHDB_ATTACHMENT_DATABASE
COUCHDB_USERNAME = settings.COUCHDB_USERNAME
COUCHDB_PASSWORD = settings.COUCHDB_PASSWORD
COUCHDB_URL = settings.COUCHDB_URL

def get_dbs_name():
    client = CouchDB(COUCHDB_USERNAME, COUCHDB_PASSWORD, url=COUCHDB_URL, connect=True, auto_renew=True)
    return client.all_dbs()

def get_db(db=COUCHDB_DATABASE):
    client = CouchDB(COUCHDB_USERNAME, COUCHDB_PASSWORD, url=COUCHDB_URL, connect=True, auto_renew=True)
    return client[db]


def upload_file(file, db=COUCHDB_ATTACHMENT_DATABASE):
    attachment_db = get_db(db)
    attachment = attachment_db.create_document({})
    return attachment.put_attachment(file.name, file.content_type, file)


def bulk_delete(db_client, documents):
    docs_to_delete = list()
    for d in documents:
        d['_deleted'] = True
        docs_to_delete.append(d)
    return db_client.bulk_docs(docs_to_delete)


def bulk_update(db_client, edited_documents):
    return db_client.bulk_docs(edited_documents)


def update_cloudant_document(db, doc_id, doc_new: dict, dict_of_list_values: dict = {}, attachments=[]):
    """
    dict_of_list_values: dict : content as key the attribut of the document who have as value as list and the values of 
    this key are the attributes than we'll modify their values
    """
    _p = {}
    try:
        from cloudant.document import Document
        _p = Document(db, doc_id)
        
        for k, v in doc_new.items():
            if k in list(dict_of_list_values.keys()): #if we have the attributes list to modify
                attr = []
                for i in range(len(v)): #Range the interval of the list of the attribut
                    elt = v[i].copy()
                    new_elt = v[i].copy()

                    if k == "attachments" and attachments: #if we have the attachments to modify
                        for elt_attach in attachments: #Go through the attachments
                            if elt_attach.get("name") and elt_attach.get("name") == elt.get("name"):
                                elt = attachments[i]

                    for _v in dict_of_list_values[k]: # Go through the attributs list of the doc attr than we going modify
                        if elt.get(_v):
                            elt[_v] = new_elt.get(_v)
                    attr.append(elt)

                _p.field_set(_p, k, attr)
                continue
            
            try:
                _p.field_set(_p, k, v)
            except:
                pass
            
        _p.save()
    except Exception as exc:
        print(exc)
        return {}
    return _p



def upload_file_s3(file, split=True, sepator="?"):
    file_directory_within_bucket = 'proof_of_work/'
    file_path_within_bucket = os.path.join(
        file_directory_within_bucket,
        f'{int(time.time())}_{file.name}'
    )

    media_storage = S3Boto3Storage()

    if not media_storage.exists(file_path_within_bucket):  # avoid overwriting existing file
        media_storage.save(file_path_within_bucket, file)
        file_url = media_storage.url(file_path_within_bucket)

        return file_url.split(sepator)[0] if split else file_url
    
    return None