from cloudant.client import CouchDB
from django.conf import settings

COUCHDB_DATABASE = settings.COUCHDB_DATABASE
COUCHDB_ATTACHMENT_DATABASE = settings.COUCHDB_ATTACHMENT_DATABASE
COUCHDB_USERNAME = settings.COUCHDB_USERNAME
COUCHDB_PASSWORD = settings.COUCHDB_PASSWORD
COUCHDB_URL = settings.COUCHDB_URL


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
