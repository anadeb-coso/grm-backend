"""Commandes export/import de la base PostgreSQL du MGP (dashboard/management/commands), contre
les bases de TEST : aller-retour par ID, recalage de `updated_at` pour que les mobiles
re-téléchargent les données importées, et refus de toute base qui n'est pas celle du MGP (en
particulier la base `mis` partagée avec la CDD et le SIG)."""
import io
import json
import zipfile
from datetime import datetime, timezone as dt_timezone
from urllib.parse import quote

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections

from issue.models import IssueStatus

OLD = datetime(2020, 1, 1, tzinfo=dt_timezone.utc)

FORMATS = [
    ('export_postgres_db', 'import_postgres_db', 'grm.zip'),
    ('export_postgres_db_sql', 'import_postgres_db_sql', 'grm.sql'),
]


def pg_url(alias):
    """URL de la base de TEST `alias` (jamais une vraie base)."""
    s = connections[alias].settings_dict
    if s['ENGINE'] != 'django.db.backends.postgresql':
        pytest.skip(f'base `{alias}` non PostgreSQL')
    assert s['NAME'].startswith('test_'), s['NAME']
    return (f"postgres://{quote(s['USER'] or '')}:{quote(s['PASSWORD'] or '')}"
            f"@{s['HOST'] or 'localhost'}:{s['PORT'] or 5432}/{s['NAME']}")


def run(command, **options):
    call_command(command, stdout=io.StringIO(), **options)


@pytest.fixture
def exported_status(tmp_path):
    """Un statut exporté avec un `updated_at` ancien, puis modifié après l'export."""
    def make(export_cmd, filename):
        status = IssueStatus.objects.create(name='Enregistrée')
        IssueStatus.objects.filter(pk=status.pk).update(updated_at=OLD)
        out = tmp_path / filename
        run(export_cmd, url=pg_url('default'), output=str(out))
        IssueStatus.objects.filter(pk=status.pk).update(name='Modifiée après export')
        return status, out
    return make


# L'export/import passe par sa propre connexion psycopg2 : les données doivent être validées.
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('export_cmd, import_cmd, filename', FORMATS)
def test_import_restores_rows_by_id_and_makes_mobiles_pull_them_again(
        exported_status, export_cmd, import_cmd, filename):
    status, out = exported_status(export_cmd, filename)
    started = datetime.now(dt_timezone.utc)

    run(import_cmd, url=pg_url('default'), file=str(out))

    status.refresh_from_db()
    assert status.name == 'Enregistrée'
    # Postérieur au `last_pulled_at` de tout appareil : renvoyé au prochain pull incrémental.
    assert status.updated_at >= started


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('export_cmd, import_cmd, filename', FORMATS)
def test_no_resync_mobiles_keeps_the_exported_timestamps(
        exported_status, export_cmd, import_cmd, filename):
    status, out = exported_status(export_cmd, filename)

    run(import_cmd, url=pg_url('default'), file=str(out), no_resync_mobiles=True)

    status.refresh_from_db()
    assert status.name == 'Enregistrée'
    assert status.updated_at == OLD


@pytest.mark.django_db(databases=['default', 'mis'])
@pytest.mark.parametrize('export_cmd, import_cmd, filename', FORMATS)
def test_refuses_the_shared_mis_database(tmp_path, export_cmd, import_cmd, filename):
    out = tmp_path / filename
    with pytest.raises(CommandError, match="n'est pas celle du MGP"):
        run(export_cmd, url=pg_url('mis'), output=str(out))
    assert not out.exists()

    run(export_cmd, url=pg_url('default'), output=str(out))
    with pytest.raises(CommandError, match="n'est pas celle du MGP"):
        run(import_cmd, url=pg_url('mis'), file=str(out), drop_all_tables=True, noinput=True)
    assert 'administrativelevels_administrativelevel' in connections['mis'].introspection.table_names()


def test_refuses_exports_of_another_platform(tmp_path):
    """Un export produit par les commandes de la CDD est refusé avant toute connexion."""
    cdd_zip = tmp_path / 'cdd.zip'
    with zipfile.ZipFile(cdd_zip, 'w') as zf:
        zf.writestr('manifest.json', json.dumps({'format': 'cdd-pg-snapshot', 'version': 1}))
    cdd_sql = tmp_path / 'cdd.sql'
    cdd_sql.write_text('-- cdd-pg-snapshot-sql v1\n', encoding='utf-8')
    url = 'postgres://nobody@127.0.0.1:1/test_never_reached'

    with pytest.raises(CommandError, match='attendu un export du MGP'):
        run('import_postgres_db', url=url, file=str(cdd_zip))
    with pytest.raises(CommandError, match="n'est pas un export du MGP"):
        run('import_postgres_db_sql', url=url, file=str(cdd_sql))
