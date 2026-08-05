from datetime import datetime
from operator import itemgetter
from cryptography.fernet import Fernet
import base64
import os
import magic
import shortuuid as uuid
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile
from io import BytesIO

from django.template.defaultfilters import date as _date
from administrativelevels import models as administrativelevels_models
from administrativelevels.serializers import AdministrativeLevelSerializer
from grm.my_librairies import get_download_folder, download_file
from grm.call_objects_from_other_db import mis_objects_call


def sort_dictionary_list_by_field(list_to_be_sorted, field, reverse=False):
    return sorted(list_to_be_sorted, key=itemgetter(field), reverse=reverse)


def get_month_range(start, end=datetime.now(), fmt="Y F"):
    start = start.month + 12 * start.year
    end = end.month + 12 * end.year
    months = list()
    for month in range(start - 1, end):
        y, m = divmod(month, 12)
        months.insert(0, (f'{y}-{m+1}', _date(datetime(y, m + 1, 1), fmt)))
    return months


def unix_time_millis(dt):
    epoch = datetime.utcfromtimestamp(0)
    return int((dt - epoch).total_seconds() * 1000)


def get_administrative_region_choices_using_mis(empty_choice=True):
    """Équivalent Postgres (base `mis`) de l'ancienne `get_administrative_region_choices`
    (CouchDB) : liste des régions (enfants directs du pays racine, `parent__isnull=True`)."""
    country = mis_objects_call.filter_objects(
        administrativelevels_models.AdministrativeLevel, parent__isnull=True, type='Country'
    ).first()
    choices = []
    if country:
        regions = mis_objects_call.filter_objects(
            administrativelevels_models.AdministrativeLevel, parent_id=country.id,
        )
    else:
        regions = mis_objects_call.filter_objects(
            administrativelevels_models.AdministrativeLevel, parent__isnull=True
        )
    choices = [(str(r.id), r.name) for r in regions]

    if empty_choice:
        choices = [('', '')] + choices
    return choices


def get_administrative_regions_by_level_using_mis(level=None):
    """Équivalent Postgres (base `mis`) de l'ancienne `get_administrative_regions_by_level`
    (CouchDB) : enfants directs du premier niveau de type `level` (ou du pays racine si `level`
    est omis) — même comportement de repli que l'original."""
    if level:
        adls = mis_objects_call.filter_objects(
            administrativelevels_models.AdministrativeLevel, type=level,
        )
    else:
        parent = mis_objects_call.filter_objects(
            administrativelevels_models.AdministrativeLevel, parent__isnull=True, type='Country'
        ).first()
    if parent:
        adls = mis_objects_call.filter_objects(
            administrativelevels_models.AdministrativeLevel, parent_id=parent.id,
        )
    else:
        adls = mis_objects_call.filter_objects(
            administrativelevels_models.AdministrativeLevel, parent__isnull=True
        )
    return [
        {
            "administrative_id": str(c.id),
            "name": c.name,
            "administrative_level": c.type,
            "type": "administrative_level",
            "parent_id": str(c.parent_id) if c.parent_id else None,
        }
        for c in adls
    ]


def _model_choices(queryset, empty_choice):
    """Construit une liste `(legacy_id, name)` à partir d'un queryset Postgres de référentiel
    `issue.models` — remplace les anciens appels `grm_db.get_query_result({"type": ...})`
    (dashboard web, désormais migré). `legacy_id` est utilisé comme clé plutôt que le pk UUID
    pour rester compatible avec le code existant qui compare ces ids à des entiers littéraux."""
    choices = [(obj.legacy_id, obj.name) for obj in queryset]
    if empty_choice:
        choices = [('', '')] + choices
    return choices


def get_issue_age_group_choices(empty_choice=True):
    from issue.models import IssueAgeGroup
    return _model_choices(IssueAgeGroup.objects.all(), empty_choice)


def get_issue_citizen_group_1_choices(empty_choice=True):
    from issue.models import IssueCitizenGroup1
    return _model_choices(IssueCitizenGroup1.objects.all(), empty_choice)


def get_issue_citizen_group_2_choices(empty_choice=True):
    from issue.models import IssueCitizenGroup2
    return _model_choices(IssueCitizenGroup2.objects.all(), empty_choice)


def get_issue_type_choices(empty_choice=True):
    from issue.models import IssueType
    return _model_choices(IssueType.objects.all(), empty_choice)


def get_issue_category_choices(empty_choice=True):
    from issue.models import IssueCategory
    return _model_choices(IssueCategory.objects.all(), empty_choice)


def get_issue_status_choices(empty_choice=True):
    from issue.models import IssueStatus
    return _model_choices(IssueStatus.objects.all(), empty_choice)


def get_auto_increment_id_using_postgres():
    """Équivalent Postgres de l'ancienne `get_auto_increment_id` (vue CouchDB
    `issues/auto_increment_id_stats`)."""
    from django.db.models import Max
    from issue.models import Issue
    max_auto_increment_id = Issue.objects.aggregate(m=Max('auto_increment_id'))['m'] or 0
    return max_auto_increment_id + 1


def get_base_administrative_id_using_mis(administrative_id, base_parent_id=None):
    """Remonte la chaîne des ancêtres de `administrative_id` jusqu'au niveau "région" attendu par
    `get_administrative_region_choices_using_mis()` (le premier sélecteur en cascade des
    formulaires de saisie/résumé d'issue).

    `get_administrative_region_choices_using_mis()` gère deux cas : s'il existe un noeud
    `type='Country'` dans `mis`, les choix sont ses enfants directs (les régions) ; sinon (cas réel
    de cette base `mis`, qui ne modélise pas de niveau "Country" séparé — la région est elle-même
    la racine, `parent_id IS NULL`), les choix sont directement les enregistrements sans parent.
    Cette fonction doit donc s'arrêter au même niveau, faute de quoi l'id renvoyé (ex. une
    préfecture) ne correspond à aucune `<option>` du sélecteur : rien ne s'affiche pré-sélectionné
    sur la page de résumé (/new-issue-step-5/) alors que la localité avait bien été enregistrée à
    l'étape précédente."""
    has_country_level = mis_objects_call.filter_objects(
        administrativelevels_models.AdministrativeLevel, parent__isnull=True, type='Country'
    ).exists()

    base_administrative_id = administrative_id
    while True:
        parent = get_parent_administrative_level_using_mis(administrative_id)

        if not parent:
            # `administrative_id` n'a pas de parent : c'est une racine. Sans niveau Country
            # séparé, c'est elle-même le niveau région à retourner ; avec un niveau Country, le
            # niveau région est l'enfant juste en dessous, déjà mémorisé dans `base_administrative_id`.
            if not has_country_level:
                base_administrative_id = administrative_id
            break

        base_administrative_id = administrative_id
        administrative_id = parent['administrative_id']
        if base_parent_id and parent['administrative_id'] == base_parent_id:
            break
    return base_administrative_id

def get_ancestor_administrative_id_by_type_using_mis(administrative_id, level_type):
    """Remonte la chaîne des ancêtres de `administrative_id` (inclus) jusqu'à trouver un niveau de
    type `level_type` (ex. 'Region', 'Prefecture', 'Commune', 'Canton', 'Village') et renvoie son
    id — utilisé par `dashboard/diagnostics/views.py::IssuesStatisticsView` pour regrouper les
    issues par niveau administratif explicitement choisi (filtre `administrative_level_type`),
    indépendamment du niveau où l'issue a été enregistrée.

    Renvoie `None` si aucun ancêtre de ce type n'existe : c'est le cas quand l'issue a été
    enregistrée à un niveau plus proche de la racine que `level_type` (ex. une issue enregistrée
    au niveau Région n'a pas d'ancêtre "Village", Village étant un niveau plus fin qu'une région,
    pas un ancêtre) — cette issue est alors exclue des statistiques pour ce type-là plutôt que
    rattachée arbitrairement à l'un de ses descendants."""
    obj = mis_objects_call.filter_objects(
        administrativelevels_models.AdministrativeLevel, id=administrative_id
    ).first()
    while obj:
        if obj.type == level_type:
            return obj.id
        obj = obj.parent
    return None


def get_parent_administrative_level_using_mis(administrative_id):
    parent = None
    
    obj = mis_objects_call.filter_objects(administrativelevels_models.AdministrativeLevel, id=administrative_id).first()
    
    if obj and obj.parent:
        parent = {
            "administrative_id": str(obj.parent.id),
            "name": obj.parent.name,
            "administrative_level": obj.parent.type,
            "type": "administrative_level",
            "parent_id": str(obj.parent.parent.id) if obj.parent.parent else None,
            "latitude": None,
            "longitude": None
        }

    return parent

def belongs_to_region_using_mis(adl_db, child_administrative_id, parent_administrative_id, user=None):
    if parent_administrative_id == child_administrative_id:
        belongs = True
    else:
        belongs = child_administrative_id in get_administrative_level_descendants_using_mis(adl_db, parent_administrative_id, [], user)
    return belongs

def get_administrative_level_descendants_using_mis(adl_db, parent_id, ids, user=None):
    """Renvoie tous les descendants stricts de `parent_id` (id spécial `1` = tout le pays, cf.
    `AdministrativeLevelsView`/`GovernmentWorker.administrative_id`), sans lui-même.

    Parcours niveau par niveau (une requête SQL par profondeur) plutôt que récursif noeud par
    noeud (une requête par appel) : l'ancienne implémentation déclenchait potentiellement plusieurs
    centaines de requêtes séquentielles vers `mis` pour une seule région (mesuré : 475 requêtes
    pour KARA) — assez pour dépasser le timeout serveur et provoquer un 500 sur
    `/api/administrative-levels/` pour un agent dont le périmètre couvre une région entière.
    L'ordre des ids retournés change (parcours en largeur au lieu d'un ordre post-order), mais
    tous les appelants ne s'en servent que comme un ensemble d'ids pour filtrer/tester
    l'appartenance (`+=`, `.update()`, `in ...`), jamais pour un affichage ordonné."""
    if not parent_id:
        return ids

    if int(parent_id) == 1:
        # Cas spécial "portée nationale" : les régions elles-mêmes comptent comme descendantes
        # (l'id 1 est une racine virtuelle, pas un vrai niveau administratif).
        frontier = list(
            administrativelevels_models.AdministrativeLevel.objects.using('mis')
            .filter(type="Region").values_list('id', flat=True)
        )
    else:
        # Enfants directs de `parent_id` — pas `parent_id` lui-même, qui n'est jamais inclus dans
        # le résultat (descendants STRICTS).
        frontier = list(
            administrativelevels_models.AdministrativeLevel.objects.using('mis')
            .filter(parent_id=int(parent_id)).values_list('id', flat=True)
        )

    while frontier:
        ids.extend(str(node_id) for node_id in frontier)
        frontier = list(
            administrativelevels_models.AdministrativeLevel.objects.using('mis')
            .filter(parent_id__in=frontier).values_list('id', flat=True)
        )

    return ids

def get_related_region_with_specific_level_using_mis(administrative_id, level):
    """Équivalent Postgres (base `mis`) de l'ancienne `get_related_region_with_specific_level`
    (CouchDB) : remonte les ancêtres depuis `administrative_id` jusqu'à trouver un niveau de type
    `level` ; si jamais trouvé, retourne le dernier niveau atteint (même repli que l'original)."""
    try:
        region = mis_objects_call.filter_objects(
            administrativelevels_models.AdministrativeLevel, id=int(administrative_id),
        ).first()
    except (TypeError, ValueError):
        return None
    if region is None:
        return None
    while region.parent and region.parent_id and region.type != level:
        next_region = mis_objects_call.filter_objects(
            administrativelevels_models.AdministrativeLevel, id=region.parent_id,
        ).first()
        if next_region is None:
            break
        region = next_region
    return {
        "administrative_id": str(region.id),
        "name": region.name,
        "administrative_level": region.type,
        "type": "administrative_level",
        "parent_id": str(region.parent_id) if region.parent_id else None,
        "latitude": None,
        "longitude": None,
    }


def get_administrative_region_name_using_mis(administrative_id):
    """Équivalent Postgres (base `mis`) de l'ancienne `get_administrative_region_name` (CouchDB) :
    nom complet "Village, Canton, Préfecture, Région" en remontant les ancêtres."""
    not_found_message = f'[Missing region with administrative_id "{administrative_id}"]'
    if not administrative_id:
        return not_found_message

    region_names = []
    try:
        region = mis_objects_call.filter_objects(
            administrativelevels_models.AdministrativeLevel, id=int(administrative_id),
        ).first()
    except (TypeError, ValueError):
        region = None

    if region is None:
        return not_found_message

    while region is not None:
        region_names.append(region.name)
        region = region.parent

    return ', '.join(region_names)


def get_child_administrative_regions_using_mis(adl_db, parent_id, user=None):
    data_ser = []
    if parent_id:
        if int(parent_id) == 1:
            data = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(type="Region").filter_by_government_worker(user)
        else:
            data = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(parent_id=int(parent_id)).filter_by_government_worker(user)
    
    for obj in data:
        obj_ser = AdministrativeLevelSerializer(obj).data
        obj_ser["administrative_id"] = str(obj.id)
        obj_ser["parent_id"] = str(obj.parent.id) if obj.parent else None
        obj_ser["administrative_level"] = obj.type
        obj_ser["type"] = "administrative_level"
        data_ser.append(obj_ser)
    return data_ser

def datetime_str(datetime_now = None):
    if not datetime_now:
        datetime_now = datetime.now()
        
    # month = str(datetime_now.month) if datetime_now.month > 9 else ("0"+str(datetime_now.month))
    # day = str(datetime_now.day) if datetime_now.day > 9 else ("0"+str(datetime_now.day))
    # return f"{str(datetime_now.year)}-{month}-{str(day)} {str(datetime_now.hour)}:{str(datetime_now.minute)}:{str(datetime_now.second)}"
    return datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')

def cryptography_fernet_key(password):
    if password:
        if len(password) > 7:
            password = password[:7]
        elif len(password) < 7:
            password = password + ((7-len(password)) * "0")
    else:
        password = "0000000"
    k = bytes(password, 'utf-32')
    return base64.urlsafe_b64encode(k)

def cryptography_fernet_encrypt(data, password, _type="txt", filename=None):
    # fernet = Fernet(key)
    # return fernet.encrypt(text.encode())
    key = cryptography_fernet_key(password)
    fernet = Fernet(key)
    if _type == "file":
        # Read the content of the original file
        file_content = data.read()
        
        # Encrypt the file content using the encryption key
        encrypted_content = fernet.encrypt(file_content)

        # Save the encrypted content to the file
        # with open(os.path.join(get_download_folder.get_download_folder(), f'encrypt_{filename}'), 'wb') as encrypted_file_obj:
        #     encrypted_file_obj.write(encrypted_content)
        #     encrypted_file_obj.close()

        #     file = open(os.path.join(get_download_folder.get_download_folder(), f'encrypt_{filename}'), 'rb')
        #     file_content = file.read()
        #     mime_type, file_extension = get_file_type(file_content)
        #     return convert_buffered_to_InMemoryUploadedFile(file_content, f'encrypt_{filename}', mime_type)
        return convert_buffered_to_InMemoryUploadedFile(encrypted_content, f'encrypt_{filename if filename else str(uuid.uuid())}' if not filename or 'encrypt_' not in filename else filename, data.content_type)
        
    else:
        return fernet.encrypt(data.encode())
    

def cryptography_fernet_decrypt(data, password, _type="txt", filename=None):
    key = cryptography_fernet_key(password)
    fernet = Fernet(key)
    if _type == "file":
        # Read the content of the original file
        file_content = data #.read()
        filename = filename.replace("encrypt_", "decrypt_")
        
        # Encrypt the file content using the encryption key
        decrypted_content = fernet.decrypt(file_content)
        # with open(os.path.join(get_download_folder.get_download_folder(), f'decrypt_{filename}'), 'wb') as decrypted_file_obj:
        #     decrypted_file_obj.write(decrypted_content)
        #     decrypted_file_obj.close()
        #     return decrypted_file_obj

        mime_type, file_extension = get_file_type(decrypted_content)
        return download_file.download_file(decrypted_content, filename, mime_type, True)

    return fernet.decrypt(convert_str_bytes_to_bytes(data)).decode()

def convert_str_bytes_to_bytes(text) -> bytes:
    return bytes(text[2:][:-1].encode())

def get_file_type(file_content):
    # Use python-magic to identify the file type
    mime_type = magic.from_buffer(file_content, mime=True)
    file_extension = magic.from_buffer(file_content, True)

    return mime_type, file_extension

def convert_buffered_to_InMemoryUploadedFile(file_content, file_name, content_type):
    # Create an InMemoryUploadedFile object
    uploaded_file = InMemoryUploadedFile(
        file=BytesIO(file_content),
        field_name=None,
        name=file_name,
        content_type=content_type,
        size=len(file_content),
        charset=None
    )

    return uploaded_file

def delete_file_on_download_file(file):
    if os.path.exists(os.path.join(get_download_folder.get_download_folder(), file.name)):
        os.remove(os.path.join(get_download_folder.get_download_folder(), file.name))