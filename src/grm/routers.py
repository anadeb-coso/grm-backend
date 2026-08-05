class MisRouter:
    """Route l'app `administrativelevels` vers la base MySQL `mis` (référentiel géré ailleurs,
    voir CLAUDE.md §2.1), tout le reste vers `default` (Postgres). Complète, sans le remplacer,
    le pattern manuel `.using('mis')` / `grm.call_objects_from_other_db.mis_objects_call` déjà
    utilisé dans le code existant : ces appels explicites continuent de fonctionner (ils forcent
    déjà le bon alias), ce routeur permet en plus aux nouvelles FK cross-db (ex.
    `Issue.administrative_region`) de résoudre automatiquement sans `.using('mis')` explicite.

    ⚠️ `allow_migrate` renvoie toujours `False` pour `administrativelevels`, y compris en test :
    cette app n'a et n'aura JAMAIS de migration dans grm-backend. `mis` appartient au projet
    `cosomis`, qui reste l'unique source de vérité de son schéma (CLAUDE.md §2.1). Les tests qui
    ont besoin d'un `AdministrativeLevel` mockent l'accès à ce modèle (voir
    sync/tests/test_sync.py) plutôt que de créer un schéma local, même dans une base de test
    jetable. Ne changez jamais cette valeur par défaut sans relire l'incident qui a motivé ce
    commentaire : pointer un jour `DATABASES['mis']['TEST']['NAME']` vers le nom réel de la base
    a causé un DROP DATABASE accidentel de `mis` via le test runner Django.
    """

    mis_apps = {'administrativelevels'}

    def db_for_read(self, model, **hints):
        return 'mis' if model._meta.app_label in self.mis_apps else None

    def db_for_write(self, model, **hints):
        return 'mis' if model._meta.app_label in self.mis_apps else None

    def allow_relation(self, obj1, obj2, **hints):
        db_set = {'default', 'mis'}
        if obj1._state.db in db_set and obj2._state.db in db_set:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.mis_apps:
            return False
        return db == 'default'
