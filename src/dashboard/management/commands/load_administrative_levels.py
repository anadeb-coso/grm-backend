import csv
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from client import bulk_update, get_db

COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL = settings.COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL

class Command(BaseCommand):
    help = 'Loads administrative levels from csv file to CouchDB'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Absolute path to csv file')

    def handle(self, *args, **kwargs):
        adl_db = get_db(COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL)

        try:
            country_administrative_id = adl_db.get_query_result(
                {
                    "type": 'administrative_level',
                    "parent_id": None,
                }
            )[:][0]['administrative_id']
        except Exception as e:
            raise CommandError(f'Failed to get country administrative level {e}')

        file_path = kwargs['file_path']

        try:
            with open(file_path, newline='') as csvfile:
                reader = csv.reader(csvfile, delimiter=';', quotechar='"')
                headers = []
                for row in reader:
                    headers = row
                    break
                created = 0
                docs_to_update = []
                for row in reader:
                    current_parent_id = country_administrative_id
                    doc_data = dict(zip(headers, row))
                    try:
                        latitude = float(doc_data['Latitude'].replace(',', '.'))
                        longitude = float(doc_data['Longitude'].replace(',', '.'))
                    except TypeError as e:
                        self.stdout.write(
                            self.style.ERROR(f'Invalid value in line {reader.line_num} for latitude/longitude. {e}'))
                        continue

                    for administrative_level, name in list(doc_data.items())[2:]:
                        administrative_level_doc = adl_db.get_query_result(
                            {
                                "type": 'administrative_level',
                                "name": name,
                                "administrative_level": administrative_level,
                                "parent_id": current_parent_id,
                            }
                        )[:]

                        if administrative_level_doc:
                            doc = administrative_level_doc[0]
                            to_update = not doc['latitude'] or not doc['longitude']
                            if not doc['latitude']:
                                doc['latitude'] = latitude
                            if not doc['longitude']:
                                doc['longitude'] = latitude
                            if to_update:
                                docs_to_update.append(doc)
                        else:
                            doc = {
                                "type": 'administrative_level',
                                "administrative_id": str(time.time()).replace('.', ''),
                                "administrative_level": administrative_level,
                                "name": name,
                                "latitude": latitude,
                                "longitude": longitude,
                                "parent_id": current_parent_id,
                            }

                            adl_db.create_document(doc)
                            created += 1

                        current_parent_id = doc['administrative_id']

                updated = len(bulk_update(adl_db, docs_to_update))

            self.stdout.write(self.style.SUCCESS(f'Successfully created {created} administrative levels'))
            self.stdout.write(self.style.SUCCESS(f'Successfully updated {updated} administrative levels'))

        except IOError as e:
            raise CommandError(f'Failed to open file {e}')
