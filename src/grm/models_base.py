import json
import uuid

from django.db import models


def safe_json_value(value, max_depth=3):
    """Retourne la vraie valeur (dict/list/...) d'un `JSONField` même quand elle a été stockée
    double-encodée : le client mobile (WatermelonDB) sérialise ses colonnes `@json` en texte côté
    SQLite local (cf. grm-frontend/src/database/schema.js) et le protocole de sync transmet cette
    chaîne telle quelle au push (sync/views.py) ; DRF/`JSONField` l'accepte comme une valeur JSON
    valide à part entière (une chaîne EST du JSON valide) et la stocke donc telle quelle plutôt que
    de la décoder une seconde fois — `issue.location_info` renvoie alors un `str` contenant du JSON
    au lieu du `dict` attendu. Décode tant que la valeur reste une chaîne, avec une limite de
    profondeur pour ne jamais boucler sur une chaîne qui ressemble à du JSON par coïncidence."""
    for _ in range(max_depth):
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            break
    return value


class TimestampedSyncModel(models.Model):
    """Base commune aux modèles synchronisés avec le mobile via WatermelonDB : UUID stable
    (généré côté client dès la création locale, cf. grm-frontend/src/database/utils/createWithId.js),
    timestamps de sync et tombstone logique (pas de suppression physique, sinon la sync ne peut
    plus notifier les clients hors-ligne de la suppression)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        abstract = True


# Create your models here.
class BaseModel(models.Model):
    created_date = models.DateTimeField(auto_now_add = True, blank=True, null=True)
    updated_date = models.DateTimeField(auto_now = True, blank=True, null=True)

    class Meta:
        abstract = True
    
    def save_and_return_object(self):
        super().save()
        return self