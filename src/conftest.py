import pytest

MIS_ALIAS = 'mis'


@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker):
    """Complète la création des bases de test : l'app `administrativelevels` (base `mis`) n'a
    aucune migration dans grm-backend (grm/routers.py::MisRouter.allow_migrate renvoie toujours
    False), la base de test `mis` est donc créée vide par le test runner. On y crée ici les
    tables des modèles de cette app, pour les tests qui déclarent la base `mis`.

    Garde-fou : on n'écrit que dans une base dont le nom commence par `test_` (cf. l'incident de
    suppression de la vraie base `mis` documenté dans grm/routers.py et grm/test_settings.py)."""
    from django.apps import apps
    from django.conf import settings
    from django.db import connections

    if MIS_ALIAS not in settings.DATABASES:
        return

    connection = connections[MIS_ALIAS]
    name = connection.settings_dict['NAME']
    if not str(name).startswith('test_'):
        raise RuntimeError(f"Refus de créer des tables dans la base `{name}` : ce n'est pas une base de test.")

    with django_db_blocker.unblock():
        existing = set(connection.introspection.table_names())
        with connection.schema_editor() as editor:
            for model in apps.get_app_config('administrativelevels').get_models():
                if model._meta.db_table not in existing:
                    editor.create_model(model)
