"""Exporte, depuis la base MySQL historique de `grm-backend` (celle que l'application utilisait
avant la bascule vers PostgreSQL, cf. CLAUDE.md §5) — PAS les données CouchDB, qui ont leurs
propres scripts (`migrate_grm_*.py`/`migrate_eadls.py`, CLAUDE.md §6) — les tables Django
"natives" vers un dossier de fichiers JSON, un par table, directement réimportables par
`import_mysql_legacy_data` (voir ce fichier pour la logique d'import).

Périmètre : les 7 tables de base déjà recensées et vérifiées par `scripts/verify_migration.py`
lors du premier transfert (dumpdata/loaddata, CLAUDE.md §5.3) : auth_group, authentication_user,
authentication_governmentworker, authentication_cdata, authentication_pdata,
privacy_issuecategorypassword, issue_wave — plus les 3 tables de liaison many-to-many de
`django.contrib.auth` sans lesquelles les comptes réimportés perdraient leurs rôles/permissions :
authentication_user_groups (User <-> Group), auth_group_permissions (Group <-> Permission) et
authentication_user_user_permissions (User <-> Permission). Les deux dernières sont exportées via
une jointure qui remplace `permission_id` (dont la valeur dépend de l'ordre des migrations, donc
non préservable) par la clé naturelle `(app_label, model, codename)`, réutilisée à l'import.
Config MySQL par défaut identique à ce script :
host=localhost, user=root, sans mot de passe, base `grm` (le nom de la base MySQL historique,
homonyme mais sans rapport avec la base CouchDB `grm` — deux systèmes distincts, cf. CLAUDE.md
§2.0).

Connexion en SQL brut (MySQLdb), pas via l'ORM Django : aucun alias `DATABASES` MySQL n'est
déclaré dans les settings de ce projet pour cette base (`default` est Postgres, `mis` est un
AUTRE MySQL externe sans rapport, cf. CLAUDE.md §2.1/§4.2.1) — en déclarer un troisième juste
pour cet export ponctuel alourdirait la configuration en permanence pour un besoin temporaire.

Usage :
    python manage.py export_mysql_legacy_data
    python manage.py export_mysql_legacy_data --host localhost --user root --password '' --db grm --out /chemin/vers/dossier
    python manage.py export_mysql_legacy_data --tables auth_group authentication_user
"""
import datetime
import decimal
import json
import os

import MySQLdb
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# Ordre sans importance à l'export (aucune contrainte FK n'est vérifiée en lecture), mais
# conservé identique à l'ordre de dépendance utilisé par `import_mysql_legacy_data` pour qu'un
# simple coup d'œil aux deux fichiers suffise à les comparer.
TABLES = [
    'auth_group',
    'authentication_user',
    'authentication_governmentworker',
    'authentication_cdata',
    'authentication_pdata',
    'privacy_issuecategorypassword',
    'issue_wave',
    # Tables de liaison M2M de django.contrib.auth : à importer APRÈS auth_group /
    # authentication_user (cf. ordre dans import_mysql_legacy_data).
    'authentication_user_groups',
    'auth_group_permissions',
    'authentication_user_user_permissions',
]

# Requêtes sur mesure : pour les deux tables de liaison vers `auth_permission`, on n'exporte pas
# `permission_id` (id volatile, dépend de l'ordre de création des content types / permissions à
# `migrate`) mais la clé naturelle `(app_label, model, codename)`, que `import_mysql_legacy_data`
# re-résout en `Permission` locale. On joint aussi le nom du groupe / l'email de l'utilisateur :
# côté import, les extrémités sont re-résolues par nom/email et non par id brut, car l'id n'est
# préservé que si `import_mysql_legacy_data` a tourné en premier (souvent faux en pratique :
# `migrate_eadls`/`loaddata` recréent les comptes par email avec un autre id). `SELECT *` sur
# `authentication_user_groups` suffit (les colonnes user_id/group_id y sont, l'import va chercher
# les emails/noms dans `authentication_user.json` / `auth_group.json`).
CUSTOM_QUERIES = {
    'auth_group_permissions': (
        'SELECT gp.group_id, g.name AS group_name, ct.app_label, ct.model, p.codename '
        'FROM auth_group_permissions gp '
        'JOIN auth_group g ON g.id = gp.group_id '
        'JOIN auth_permission p ON p.id = gp.permission_id '
        'JOIN django_content_type ct ON ct.id = p.content_type_id'
    ),
    'authentication_user_user_permissions': (
        'SELECT up.user_id, u.email AS user_email, ct.app_label, ct.model, p.codename '
        'FROM authentication_user_user_permissions up '
        'JOIN authentication_user u ON u.id = up.user_id '
        'JOIN auth_permission p ON p.id = up.permission_id '
        'JOIN django_content_type ct ON ct.id = p.content_type_id'
    ),
}

# Colonnes JSON stockées en texte brut par MySQL (MySQLdb ne les décode pas automatiquement,
# contrairement à un connecteur JSON-aware) : décodées explicitement à l'export pour ne pas
# produire une chaîne JSON imbriquée deux fois dans le fichier de sortie (même piège que
# `grm.models_base.safe_json_value` ailleurs dans ce projet, pour les issues `source='mobile'`).
JSON_COLUMNS = {
    'authentication_governmentworker': {'administrative_ids', 'additional_administrative_ids'},
    'issue_wave': {'administrative_ids'},
}

DEFAULT_OUTPUT_DIR = settings.BASE_DIR.parent / 'scripts' / 'mysql_legacy_export'


def _json_default(value):
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode('utf-8', errors='replace')
    raise TypeError(f'Type non sérialisable : {type(value)!r}')


class Command(BaseCommand):
    help = (
        "Exporte les tables Django historiques de la base MySQL de grm-backend (auth_group, "
        "authentication_user, authentication_governmentworker, authentication_cdata, "
        "authentication_pdata, privacy_issuecategorypassword, issue_wave, plus les liaisons M2M "
        "authentication_user_groups, auth_group_permissions, authentication_user_user_permissions) "
        "vers des fichiers JSON, un par table, réimportables via `import_mysql_legacy_data`."
    )

    def add_arguments(self, parser):
        parser.add_argument('--host', default='localhost')
        parser.add_argument('--port', type=int, default=3306)
        parser.add_argument('--user', default='root')
        parser.add_argument('--password', default='')
        parser.add_argument(
            '--db', default='grm',
            help="Nom de la base MySQL source (défaut : 'grm', cf. scripts/verify_migration.py).",
        )
        parser.add_argument(
            '--out', default=None,
            help=f"Dossier de sortie (défaut : {DEFAULT_OUTPUT_DIR}).",
        )
        parser.add_argument(
            '--tables', nargs='+', default=None,
            help="Sous-ensemble de tables à exporter (défaut : les 7 tables du périmètre §5 "
                 "+ les 3 tables de liaison M2M de django.contrib.auth).",
        )

    def handle(self, *args, **options):
        out_dir = options['out'] or str(DEFAULT_OUTPUT_DIR)
        os.makedirs(out_dir, exist_ok=True)
        tables = options['tables'] or TABLES

        try:
            conn = MySQLdb.connect(
                host=options['host'], port=options['port'], user=options['user'],
                passwd=options['password'], db=options['db'],
            )
        except Exception as exc:
            raise CommandError(f"Connexion MySQL impossible ({options['db']}@{options['host']}) : {exc}")

        manifest = {}
        try:
            for table in tables:
                with conn.cursor() as cursor:
                    cursor.execute(CUSTOM_QUERIES.get(table, f'SELECT * FROM {table}'))
                    columns = [col[0] for col in cursor.description]
                    json_columns = JSON_COLUMNS.get(table, set())
                    rows = []
                    for raw_row in cursor.fetchall():
                        row = dict(zip(columns, raw_row))
                        for col in json_columns:
                            if isinstance(row.get(col), str):
                                try:
                                    row[col] = json.loads(row[col])
                                except (TypeError, ValueError):
                                    pass  # laissé tel quel : signalé/ignoré par l'import si invalide
                        rows.append(row)

                out_path = os.path.join(out_dir, f'{table}.json')
                with open(out_path, 'w', encoding='utf-8') as f:
                    json.dump(rows, f, default=_json_default, ensure_ascii=False, indent=2)

                manifest[table] = len(rows)
                self.stdout.write(self.style.SUCCESS(f'{table}: {len(rows)} ligne(s) -> {out_path}'))
        finally:
            conn.close()

        with open(os.path.join(out_dir, '_manifest.json'), 'w', encoding='utf-8') as f:
            json.dump({
                'source_db': options['db'],
                'source_host': options['host'],
                'exported_at': datetime.datetime.now().isoformat(),
                'counts': manifest,
            }, f, ensure_ascii=False, indent=2)

        self.stdout.write(self.style.SUCCESS(f'Export terminé dans {out_dir}'))
