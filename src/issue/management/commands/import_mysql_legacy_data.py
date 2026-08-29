"""Importe dans PostgreSQL les tables Django historiques de `grm-backend` exportées par
`export_mysql_legacy_data` (CLAUDE.md §5) : auth_group, authentication_user,
authentication_governmentworker, authentication_cdata, authentication_pdata,
privacy_issuecategorypassword, issue_wave.

Rejouable sans doublon, comme `migrate_grm_*.py`/`migrate_eadls.py` (CLAUDE.md §6) — mais avec
une règle unique et volontairement stricte : **l'id de chaque objet est préservé tel quel entre
MySQL et Postgres, jamais régénéré**. `Group`/`User`/`IssueCategoryPassword`/`Wave` sont donc
tous rapprochés par `update_or_create(pk=<id MySQL>, ...)`, et toute FK vers l'une de ces tables
(`authentication_governmentworker.user_id`, `privacy_issuecategorypassword.user_id`) réutilise
l'id MySQL brut du fichier exporté sans aucune table de correspondance — puisque côté Postgres
c'est numériquement le même id. Séquences PostgreSQL remises à niveau en fin de commande pour
chaque table où un id a été forcé (sinon la prochaine création ORM "normale" entrerait en
collision, même précaution que l'option `reset sequences` de pgloader, cf.
`scripts/migrate_mysql_to_pg.load`).

⚠️ Ordre d'exécution important : cette commande doit tourner AVANT `migrate_eadls` (et plus
généralement avant toute création de `User` côté Postgres, cf. CLAUDE.md §10 item 6 — "Exécuter
§5 (MySQL → Postgres)... puis seulement lancer les scripts de migration CouchDB (§6)").
`migrate_eadls`, lui, rapproche ses `User` par email (les facilitateurs n'existant pas forcément
côté MySQL) : s'il tourne EN PREMIER et crée un `User` avec un id auto-attribué par Postgres pour
un email qui appartient aussi à un compte MySQL, cette commande ne peut plus forcer l'id MySQL
d'origine sur cet email (contrainte unique `email` déjà prise par un autre id) — le conflit est
détecté et loggé (ligne ignorée, pas d'échec de toute la commande), mais l'id ne correspondra
alors plus entre les deux systèmes pour cet utilisateur précis. Respecter l'ordre ci-dessus
l'évite entièrement : `migrate_eadls`, exécuté après, retrouve alors l'utilisateur déjà importé
via son email et réutilise son id existant sans le changer.

`created_date`/`updated_date` (`grm.models_base.BaseModel`, sur `IssueCategoryPassword`/`Wave`)
sont `auto_now_add`/`auto_now` : un `.save()` (donc `update_or_create`) ignore silencieusement
toute valeur qu'on tente d'y affecter. Comme ailleurs dans ce projet (cf. sync/views.py),
`QuerySet.update()` ne déclenche jamais `auto_now` — c'est le seul moyen de restaurer les dates
d'origine issues de MySQL, via un second passage après la création/mise à jour.

Le mot de passe utilisateur est déjà au format `pbkdf2_sha256$...` (hash natif Django) :
affectation directe, aucun rehashage (même raisonnement que `migrate_eadls.py`).

⚠️ Désactive les mêmes signaux `post_save`/`post_delete` que `migrate_eadls.py` pendant l'import
des `User`/`GovernmentWorker` (email SMTP réel + écriture CouchDB sinon).

Usage :
    python manage.py export_mysql_legacy_data                  # d'abord : lit MySQL, écrit du JSON
    python manage.py import_mysql_legacy_data                   # ensuite : lit le JSON, écrit Postgres
    python manage.py import_mysql_legacy_data --input /chemin
    python manage.py import_mysql_legacy_data --dry-run          # simule (rollback en fin de transaction)
"""
import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, connection, transaction
from django.db.models.signals import post_delete, post_save
from django.utils.dateparse import parse_date, parse_datetime

import authentication.models as auth_models
from issue.models import Wave
from privacy.models import IssueCategoryPassword

User = get_user_model()

DEFAULT_INPUT_DIR = settings.BASE_DIR.parent / 'scripts' / 'mysql_legacy_export'


class _DryRunRollback(Exception):
    """Signal interne pour faire échouer volontairement la transaction englobante en mode
    `--dry-run`, après que toutes les opérations aient été exécutées (donc comptabilisées/
    affichées) mais avant tout `COMMIT` réel."""


def _load(input_dir, table):
    path = os.path.join(input_dir, f'{table}.json')
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _dt(value):
    """Les dates/heures sont sérialisées en ISO-8601 par `export_mysql_legacy_data` (via
    `datetime.isoformat()`) — reconverties ici en objets `datetime`/`date` pour les champs
    `DateTimeField`/`DateField`. `None`/chaîne vide préservés tels quels (champs optionnels).

    Une valeur sans fuseau (cas MySQL le plus courant, colonnes `DATETIME` naïves) redevient un
    `datetime` naïf ; avec `USE_TZ=True`/`TIME_ZONE='UTC'` (settings.py), Django l'interprète
    alors comme de l'UTC lors de l'écriture — cohérent si l'ancienne application tournait déjà en
    UTC (hypothèse la plus courante, à vérifier si les dates restaurées semblent décalées)."""
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is not None:
        return parsed
    return parse_date(value)


def _restore_base_model_timestamps(model, pk, created_date, updated_date):
    updates = {}
    if created_date is not None:
        updates['created_date'] = created_date
    if updated_date is not None:
        updates['updated_date'] = updated_date
    if updates:
        model.objects.filter(pk=pk).update(**updates)


def _reset_pg_sequence(model):
    """Remet la séquence PostgreSQL de la clé primaire au-delà du plus grand id désormais présent
    — nécessaire après avoir forcé des ids explicites via `update_or_create(pk=...)`, sinon la
    prochaine création ORM "normale" (id auto-attribué) entrerait en collision (même précaution
    documentée dans `scripts/migrate_mysql_to_pg.load`, option `reset sequences` de pgloader)."""
    table = model._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), COALESCE((SELECT MAX(id) FROM \"" + table + "\"), 1))",
            [table],
        )


class Command(BaseCommand):
    help = (
        "Importe dans PostgreSQL les tables Django historiques exportées par "
        "`export_mysql_legacy_data` (auth_group, authentication_user, "
        "authentication_governmentworker, authentication_cdata, authentication_pdata, "
        "privacy_issuecategorypassword, issue_wave), en préservant tels quels les id MySQL."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--input', default=None,
            help=f"Dossier des fichiers JSON exportés (défaut : {DEFAULT_INPUT_DIR}).",
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help="N'écrit rien en base (rollback en fin de transaction), affiche seulement les comptages.",
        )

    def handle(self, *args, **options):
        input_dir = options['input'] or str(DEFAULT_INPUT_DIR)
        if not os.path.isdir(input_dir):
            raise CommandError(f"Dossier introuvable : {input_dir} — lancez d'abord `export_mysql_legacy_data`.")
        self.dry_run = options['dry_run']

        post_save.disconnect(auth_models.create_or_update_user, sender=User)
        post_delete.disconnect(auth_models.delete_user, sender=User)
        post_save.disconnect(auth_models.set_user_government_worker, sender=auth_models.GovernmentWorker)
        post_delete.disconnect(auth_models.delete_user_government_worker, sender=auth_models.GovernmentWorker)
        try:
            try:
                with transaction.atomic():
                    self._import_groups(input_dir)
                    self._import_users(input_dir)
                    self._import_government_workers(input_dir)
                    self._import_key_data(input_dir, 'authentication_cdata', auth_models.Cdata)
                    self._import_key_data(input_dir, 'authentication_pdata', auth_models.Pdata)
                    self._import_issue_category_passwords(input_dir)
                    self._import_waves(input_dir)
                    if self.dry_run:
                        raise _DryRunRollback()
            except _DryRunRollback:
                self.stdout.write(self.style.WARNING("--dry-run : transaction annulée, rien n'a été écrit."))
        finally:
            post_save.connect(auth_models.create_or_update_user, sender=User)
            post_delete.connect(auth_models.delete_user, sender=User)
            post_save.connect(auth_models.set_user_government_worker, sender=auth_models.GovernmentWorker)
            post_delete.connect(auth_models.delete_user_government_worker, sender=auth_models.GovernmentWorker)

        if not self.dry_run:
            self.stdout.write(self.style.SUCCESS('Import terminé.'))

    def _import_groups(self, input_dir):
        rows = _load(input_dir, 'auth_group') or []
        count = 0
        skipped = 0
        for row in rows:
            if self._force_pk_update_or_create(Group, row['id'], {'name': row['name']}, natural_key_field='name'):
                count += 1
            else:
                skipped += 1
        if rows:
            _reset_pg_sequence(Group)
        self.stdout.write(
            f'auth_group: {count} ligne(s) traitée(s)' + (f', {skipped} en conflit (voir avertissements)' if skipped else '')
        )

    def _import_users(self, input_dir):
        rows = _load(input_dir, 'authentication_user') or []
        count = 0
        skipped = 0
        for row in rows:
            email = row.get('email')
            if not email:
                skipped += 1
                self.stdout.write(self.style.WARNING(
                    f"authentication_user id={row.get('id')} : pas d'email (contrainte unique du "
                    "modèle), ligne ignorée."
                ))
                continue

            defaults = {
                'email': email,
                'username': row.get('username') or email,
                'first_name': row.get('first_name') or '',
                'last_name': row.get('last_name') or '',
                'phone_number': row.get('phone_number') or '',
                'is_active': row.get('is_active', True),
                'is_staff': row.get('is_staff', False),
                'is_superuser': row.get('is_superuser', False),
            }
            if row.get('photo'):
                # Le chemin relatif est préservé tel quel (même storage/MEDIA_ROOT supposé) : les
                # fichiers physiques eux-mêmes ne sont PAS copiés par cet outil (hors périmètre
                # d'une migration de données, à traiter séparément si le stockage change).
                defaults['photo'] = row['photo']
            if row.get('date_joined'):
                defaults['date_joined'] = _dt(row['date_joined'])
            if row.get('last_login'):
                defaults['last_login'] = _dt(row['last_login'])

            user = self._force_pk_update_or_create(User, row['id'], defaults, natural_key_field='email')
            if user is None:
                skipped += 1
                continue

            if row.get('password'):
                user.password = row['password']
                user.save(update_fields=['password'])
            count += 1

        if rows:
            _reset_pg_sequence(User)
        self.stdout.write(
            f'authentication_user: {count} ligne(s) traitée(s)'
            + (f', {skipped} ignorée(s)/en conflit (voir avertissements)' if skipped else '')
        )

    def _force_pk_update_or_create(self, model, pk, defaults, natural_key_field):
        """`update_or_create(pk=pk, ...)`, en préservant STRICTEMENT l'id source (jamais de
        régénération, cf. docstring du module) — avec un filet de sécurité : si la ligne n'existe
        pas encore à cet id mais qu'une AUTRE ligne occupe déjà la valeur unique naturelle
        (`email` pour `User`, `name` pour `Group`) sous un id différent (ex. `migrate_eadls`
        exécutée avant cette commande), l'`INSERT` violerait cette contrainte unique — intercepté
        ici (savepoint dédié) pour ne pas faire échouer tout le reste de l'import, avec un
        avertissement explicite plutôt qu'un plantage silencieux ou une régénération d'id.
        Retourne l'instance en cas de succès, `None` en cas de conflit."""
        try:
            with transaction.atomic():
                obj, _created = model.objects.update_or_create(pk=pk, defaults=defaults)
                return obj
        except IntegrityError:
            natural_value = defaults.get(natural_key_field)
            conflicting = model.objects.filter(**{natural_key_field: natural_value}).exclude(pk=pk).first()
            self.stdout.write(self.style.WARNING(
                f"{model.__name__} id={pk} : impossible de préserver cet id — "
                f"{natural_key_field}={natural_value!r} appartient déjà à l'id="
                f"{getattr(conflicting, 'pk', '?')}. Cette ligne source ne sera pas importée sous "
                "un id différent (aucune régénération d'id) ; si c'est `migrate_eadls` qui a créé "
                "cette ligne en premier, relancez cette commande AVANT `migrate_eadls` pour éviter "
                "le conflit (cf. docstring du module)."
            ))
            return None

    def _import_government_workers(self, input_dir):
        rows = _load(input_dir, 'authentication_governmentworker') or []
        count = 0
        skipped = 0
        for row in rows:
            user_id = row.get('user_id')
            if user_id is None or not User.objects.filter(pk=user_id).exists():
                skipped += 1
                continue
            auth_models.GovernmentWorker.objects.update_or_create(
                user_id=user_id,
                defaults={
                    # Même repli que migrate_eadls.py : `department` n'a pas de valeur par défaut
                    # côté modèle (PositiveSmallIntegerField requis).
                    'department': row.get('department') or 1,
                    'administrative_id': row.get('administrative_id'),
                    'administrative_ids': row.get('administrative_ids') or [],
                    'additional_administrative_ids': row.get('additional_administrative_ids') or [],
                },
            )
            count += 1

        self.stdout.write(
            f'authentication_governmentworker: {count} ligne(s) traitée(s)'
            + (f', {skipped} ignorée(s) (utilisateur non importé, cf. avertissements ci-dessus)' if skipped else '')
        )

    def _import_key_data(self, input_dir, table, model):
        rows = _load(input_dir, table) or []
        for row in rows:
            model.objects.update_or_create(key=row['key'], defaults={'data': row.get('data')})
        self.stdout.write(f'{table}: {len(rows)} ligne(s) traitée(s)')

    def _import_issue_category_passwords(self, input_dir):
        rows = _load(input_dir, 'privacy_issuecategorypassword') or []
        skipped = 0
        for row in rows:
            user_id = row.get('user_id')
            if user_id is not None and not User.objects.filter(pk=user_id).exists():
                skipped += 1
                user_id = None  # FK nullable (on_delete=SET_NULL) : on n'invente pas de rattachement
            IssueCategoryPassword.objects.update_or_create(
                id=row['id'],
                defaults={
                    'issue_category_id': row.get('issue_category_id'),
                    'password': row.get('password') or '',
                    'user_id': user_id,
                    'key': row.get('key'),
                    'password_data_encrypt': row.get('password_data_encrypt'),
                },
            )
            _restore_base_model_timestamps(
                IssueCategoryPassword, row['id'], _dt(row.get('created_date')), _dt(row.get('updated_date')),
            )
        if rows:
            _reset_pg_sequence(IssueCategoryPassword)
        self.stdout.write(
            f'privacy_issuecategorypassword: {len(rows)} ligne(s) traitée(s)'
            + (f', {skipped} avec utilisateur non résolu (rattachement laissé vide)' if skipped else '')
        )

    def _import_waves(self, input_dir):
        rows = _load(input_dir, 'issue_wave') or []
        for row in rows:
            Wave.objects.update_or_create(
                id=row['id'],
                defaults={
                    'number': row.get('number'),
                    'description': row.get('description') or '',
                    'administrative_ids': row.get('administrative_ids') or [],
                    'begin': _dt(row.get('begin')),
                    'end': _dt(row.get('end')),
                },
            )
            _restore_base_model_timestamps(
                Wave, row['id'], _dt(row.get('created_date')), _dt(row.get('updated_date')),
            )
        if rows:
            _reset_pg_sequence(Wave)
        self.stdout.write(f'issue_wave: {len(rows)} ligne(s) traitée(s)')
