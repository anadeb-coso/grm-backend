"""Migre les facilitateurs (documents `adl` de la base CouchDB `eadls`) vers Postgres
(`issue.Adl` + comptes `auth.User`). Rejouable sans doublon (`update_or_create` sur
`legacy_couch_id`, l'`_id` CouchDB, et sur l'email pour les `User`).

Le mot de passe (`representative.password`) est déjà au format `pbkdf2_sha256$...` (hash natif
Django) : affectation directe, aucun rehashage.

⚠️ Désactive volontairement les signaux `post_save`/`post_delete` de `authentication.models`
pendant toute la durée de la commande : ces signaux appellent `send_code_by_mail` (email SMTP
réel) et réécrivent dans CouchDB `eadls` à chaque création/modification de `User`/
`GovernmentWorker` — sans ce garde-fou, migrer des centaines de facilitateurs réels enverrait
autant d'emails involontaires (incident déjà rencontré une fois avec `loaddata`, voir
grm/routers.py pour le contexte de l'incident cousin sur la base `mis`).

Usage : python manage.py migrate_eadls
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models.signals import post_delete, post_save
import itertools

import authentication.models as auth_models
from client import get_db
from issue.models import Adl

User = get_user_model()


class Command(BaseCommand):
    help = 'Migre les facilitateurs (adl) depuis CouchDB (eadls) vers Postgres.'

    def handle(self, *args, **options):
        post_save.disconnect(auth_models.create_or_update_user, sender=User)
        post_delete.disconnect(auth_models.delete_user, sender=User)
        post_save.disconnect(auth_models.set_user_government_worker, sender=auth_models.GovernmentWorker)
        post_delete.disconnect(auth_models.delete_user_government_worker, sender=auth_models.GovernmentWorker)

        try:
            self._migrate()
        finally:
            post_save.connect(auth_models.create_or_update_user, sender=User)
            post_delete.connect(auth_models.delete_user, sender=User)
            post_save.connect(auth_models.set_user_government_worker, sender=auth_models.GovernmentWorker)
            post_delete.connect(auth_models.delete_user_government_worker, sender=auth_models.GovernmentWorker)

    def _migrate(self):
        db = get_db(settings.COUCHDB_DATABASE)  # 'eadls'
        count = 0

        for doc in db:
            if doc.get('type') != 'adl':
                continue
            doc_id = doc['_id']

            rep = doc.get('representative') or {}
            user = None
            if rep.get('email'):
                full_name = rep.get('name') or ''
                first_name, _, last_name = full_name.partition(' ')
                user, _created = User.objects.update_or_create(
                    email=rep['email'],
                    defaults={
                        'username': rep['email'],
                        'first_name': first_name,
                        'last_name': last_name,
                        'phone_number': rep.get('phone') or '',
                        'is_active': rep.get('is_active', True),
                    },
                )
                if rep.get('password'):
                    user.password = rep['password']
                    user.save(update_fields=['password'])

            region_ids = [str(r) for r in (doc.get('administrative_regions') or []) if str(r).isdigit()]
            administrative_regions_objects = doc.get('administrative_regions_objects')
            administratives_stabilized = list(set(
                (region_ids if region_ids else []) + list(itertools.chain(*[[str(v['id']) for v in ad['villages']] for ad in (administrative_regions_objects if administrative_regions_objects else [])]))
            ))
            additional_region_ids = [
                str(r) for r in (doc.get('additional_administrative_regions') or []) if str(r).isdigit()
            ]
            additional_administrative_regions_objects = doc.get('additional_administrative_regions_objects')
            additional_administratives_stabilized = list(set(
                (additional_region_ids if additional_region_ids else []) + list(itertools.chain(*[[str(v['id']) for v in ad['villages']] for ad in (additional_administrative_regions_objects if additional_administrative_regions_objects else [])]))
            ))

            Adl.objects.update_or_create(
                legacy_couch_id=doc_id,
                defaults={
                    'name': doc.get('name') or doc.get('location_name') or (rep.get('name') or 'ADL'),
                    'location_name': doc.get('location_name'),
                    'representative': user,
                    'representative_name': rep.get('name'),
                    'department': str(doc.get('department')) if doc.get('department') is not None else None,
                    'administrative_region_ids': region_ids,
                    'smallest_administrative_level_ids': administratives_stabilized,
                    'additional_administrative_region_ids': additional_region_ids,
                    'additional_smallest_administrative_level_ids': additional_administratives_stabilized,
                },
            )


            if hasattr(user, 'governmentworker'):
                governmentworker = auth_models.GovernmentWorker.objects.get(id=user.governmentworker.id)
            else:
                governmentworker = auth_models.GovernmentWorker()
                governmentworker.user = user
                governmentworker.department = 1

            governmentworker.administrative_id = doc['administrative_region']

            governmentworker.administrative_ids = region_ids
            governmentworker.additional_administrative_ids = additional_region_ids

            governmentworker.save()

            
            count += 1

        self.stdout.write(self.style.SUCCESS(f'adls: {count} document(s) migré(s)'))
