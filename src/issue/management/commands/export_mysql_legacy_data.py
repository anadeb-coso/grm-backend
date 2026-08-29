"""Exporte, depuis la base MySQL historique de `grm-backend` (celle que l'application utilisait
avant la bascule vers PostgreSQL, cf. CLAUDE.md §5) — PAS les données CouchDB, qui ont leurs
propres scripts (`migrate_grm_*.py`/`migrate_eadls.py`, CLAUDE.md §6) — les tables Django
"natives" vers un dossier de fichiers JSON, un par table, directement réimportables par
`import_mysql_legacy_data` (voir ce fichier pour la logique d'import).

Périmètre : les 7 tables déjà recensées et vérifiées par `scripts/verify_migration.py` lors du
premier transfert (dumpdata/loaddata, CLAUDE.md §5.3) : auth_group, authentication_user,
authentication_governmentworker, authentication_cdata, authentication_pdata,
privacy_issuecategorypassword, issue_wave. Config MySQL par défaut identique à ce script :
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
]

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
        "authentication_pdata, privacy_issuecategorypassword, issue_wave) vers des fichiers "
        "JSON, un par table, réimportables via `import_mysql_legacy_data`."
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
            help="Sous-ensemble de tables à exporter (défaut : les 7 tables du périmètre §5).",
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
                    cursor.execute(f'SELECT * FROM {table}')
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
