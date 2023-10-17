from datetime import datetime
from operator import itemgetter
from cryptography.fernet import Fernet
import base64
import os
import magic
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile
from io import BytesIO

from django.template.defaultfilters import date as _date
from administrativelevels import models as administrativelevels_models
from administrativelevels.serializers import AdministrativeLevelSerializer
from grm.my_librairies import get_download_folder, download_file


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


def get_administrative_region_choices(adl_db, empty_choice=True):
    country_id = adl_db.get_query_result(
        {
            "type": 'administrative_level',
            "parent_id": None,
        }
    )[:][0]['administrative_id']
    query_result = adl_db.get_query_result(
        {
            "type": 'administrative_level',
            "parent_id": country_id,
        }
    )
    choices = list()
    for i in query_result:
        choices.append((i['administrative_id'], f"{i['name']}"))
    if empty_choice:
        choices = [('', '')] + choices
    return choices


def get_choices(query_result, empty_choice=True):
    choices = [(i['id'], i['name']) for i in query_result]
    if empty_choice:
        choices = [('', '')] + choices
    return choices


def get_issue_age_group_choices(grm_db, empty_choice=True):
    query_result = grm_db.get_query_result({"type": 'issue_age_group'})
    return get_choices(query_result, empty_choice)


def get_issue_citizen_group_1_choices(grm_db, empty_choice=True):
    query_result = grm_db.get_query_result({"type": 'issue_citizen_group_1'})
    return get_choices(query_result, empty_choice)


def get_issue_citizen_group_2_choices(grm_db, empty_choice=True):
    query_result = grm_db.get_query_result({"type": 'issue_citizen_group_2'})
    return get_choices(query_result, empty_choice)


def get_issue_type_choices(grm_db, empty_choice=True):
    query_result = grm_db.get_query_result({"type": 'issue_type'})
    return get_choices(query_result, empty_choice)


def get_issue_category_choices(grm_db, empty_choice=True):
    query_result = grm_db.get_query_result({"type": 'issue_category'})
    return get_choices(query_result, empty_choice)


def get_issue_status_choices(grm_db, empty_choice=True):
    query_result = grm_db.get_query_result({"type": 'issue_status'})
    return get_choices(query_result, empty_choice)


def get_administrative_region_name(adl_db, administrative_id):
    not_found_message = f'[Missing region with administrative_id "{administrative_id}"]'
    if not administrative_id:
        return not_found_message

    region_names = []
    has_parent = True

    while has_parent:
        docs = adl_db.get_query_result({
            "administrative_id": administrative_id,
            "type": 'administrative_level'
        })

        try:
            doc = adl_db[docs[0][0]['_id']]
            region_names.append(doc['name'])
            administrative_id = doc['parent_id']
            has_parent = administrative_id is not None
        except Exception:
            region_names.append(not_found_message)
            has_parent = False

    return ', '.join(region_names)


def get_base_administrative_id(adl_db, administrative_id, base_parent_id=None):
    base_administrative_id = administrative_id
    while True:
        parent = get_parent_administrative_level(adl_db, administrative_id)
        if parent:
            base_administrative_id = administrative_id
            administrative_id = parent['administrative_id']
            if base_parent_id and parent['administrative_id'] == base_parent_id:
                break
        else:
            break
    return base_administrative_id


def get_child_administrative_regions(adl_db, parent_id):
    data = adl_db.get_query_result(
        {
            "type": 'administrative_level',
            "parent_id": parent_id,
        }
    )
    data = [doc for doc in data]
    return data


def get_administrative_regions_by_level(adl_db, level=None):
    filters = {"type": 'administrative_level'}
    if level:
        filters['administrative_level'] = level
    else:
        filters['parent_id'] = None
    parent_id = adl_db.get_query_result(filters)[:][0]['administrative_id']
    data = adl_db.get_query_result(
        {
            "type": 'administrative_level',
            "parent_id": parent_id,
        }
    )
    data = [doc for doc in data]
    return data


def get_administrative_level_descendants(adl_db, parent_id, ids):
    data = adl_db.get_query_result(
        {
            "type": 'administrative_level',
            "parent_id": parent_id,
        }
    )
    data = [doc for doc in data]
    descendants_ids = [region["administrative_id"] for region in data]
    for descendant_id in descendants_ids:
        get_administrative_level_descendants(adl_db, descendant_id, ids)
        ids.append(descendant_id)

    return ids


def get_parent_administrative_level(adl_db, administrative_id):
    parent = None
    docs = adl_db.get_query_result({
        "administrative_id": administrative_id,
        "type": 'administrative_level'
    })

    try:
        doc = adl_db[docs[0][0]['_id']]
        if 'parent_id' in doc and doc['parent_id']:
            administrative_id = doc['parent_id']
            docs = adl_db.get_query_result({
                "administrative_id": administrative_id,
                "type": 'administrative_level'
            })
            parent = adl_db[docs[0][0]['_id']]
    except Exception:
        pass
    return parent


def get_related_region_with_specific_level(adl_db, region_doc, level):
    """
    Returns the document of type=administrative_level related to the region_doc with
    administrative_level=level. To find it, start from the region_doc and continue
    through its ancestors until it is found, if it is not found, return the region_doc
    """
    has_parent = True
    administrative_id = region_doc['administrative_id']
    while has_parent and region_doc['administrative_level'] != level:
        region_doc = get_parent_administrative_level(adl_db, administrative_id)
        if region_doc:
            administrative_id = region_doc['administrative_id']
        else:
            has_parent = False

    return region_doc


def belongs_to_region(adl_db, child_administrative_id, parent_administrative_id):
    if parent_administrative_id == child_administrative_id:
        belongs = True
    else:
        belongs = child_administrative_id in get_administrative_level_descendants(adl_db, parent_administrative_id, [])
    return belongs

def belongs_to_region_using_mis(adl_db, child_administrative_id, parent_administrative_id, user=None):
    if parent_administrative_id == child_administrative_id:
        belongs = True
    else:
        belongs = child_administrative_id in get_administrative_level_descendants_using_mis(adl_db, parent_administrative_id, [], user)
    return belongs

def get_auto_increment_id(grm_db):
    try:
        max_auto_increment_id = grm_db.get_view_result('issues', 'auto_increment_id_stats')[0][0]['value']['max']
    except Exception:
        max_auto_increment_id = 0
    return max_auto_increment_id + 1
    # date_now = datetime.now()
    # max_auto_increment_id_2 = int(float(str(max_auto_increment_id).replace(',', '.')))
    # auto_increment = int((str(date_now.timestamp()) + str(date_now.microsecond)).replace('.', ''))
    # if auto_increment <= max_auto_increment_id_2:
    #     auto_increment = max_auto_increment_id_2 + 1
    # return auto_increment


def get_administrative_level_descendants_using_mis(adl_db, parent_id, ids, user=None):
    data = []
    if parent_id:
        if int(parent_id) == 1:
            data = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(type="Region") #.filter_by_government_worker(user, False, False)
        else:
            data = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(parent_id=int(parent_id)) #.filter_by_government_worker(user, False, False)
        
    descendants_ids = [obj.id for obj in data]
    for descendant_id in descendants_ids:
        get_administrative_level_descendants_using_mis(adl_db, descendant_id, ids, user)
        ids.append(str(descendant_id))

    return ids

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
        return convert_buffered_to_InMemoryUploadedFile(encrypted_content, f'encrypt_{filename}', data.content_type)
        
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