from django.conf import settings
from django.core.management.base import BaseCommand
from grm.utils import get_administrative_region_name

from client import (
    # bulk_delete,
    bulk_update,
    get_db
)

COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE
COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL = settings.COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL


class Command(BaseCommand):

    def handle(self, *args, **options):
        eadl_db = get_db()
        adl_db = get_db(COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL)

        # docs_to_delete = [d for d in eadl_db if 'type' in d and d['type'] == 'commune']
        # communes_deleted = len(bulk_delete(eadl_db, docs_to_delete))
        #
        # self.stdout.write(self.style.SUCCESS(f'Successfully deleted {communes_deleted} communes'))

        docs = [d for d in eadl_db if 'type' in d and d['type'] == 'adl']
        docs_to_update = []
        for doc in docs:
            if 'name' not in doc or not doc['name']:
                doc['name'] = get_administrative_region_name(adl_db, doc['administrative_region'])
                docs_to_update.append(doc)
        docs_updated = len(bulk_update(eadl_db, docs_to_update))

        self.stdout.write(self.style.SUCCESS(f'Successfully updated {docs_updated} docs'))

        # grm_db = get_db(COUCHDB_GRM_DATABASE)
        # issues = [d for d in grm_db if 'commune' in d and 'type' in d and d['type'] == 'issue']
        # docs_to_update = []
        # for issue in issues:
        #     issue['administrative_region'] = {
        #         "administrative_id": issue['commune']['code'],
        #         "name": issue['commune']["name"]
        #     }
        #     del issue['commune']
        #     docs_to_update.append(issue)
        # issues_updated = len(bulk_update(grm_db, docs_to_update))
        #
        # self.stdout.write(self.style.SUCCESS(f'Successfully updated {issues_updated} issues'))
