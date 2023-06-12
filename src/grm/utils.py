from datetime import datetime
from operator import itemgetter

from django.template.defaultfilters import date as _date


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

def belongs_to_region_using_mis(adl_db, child_administrative_id, parent_administrative_id):
    if parent_administrative_id == child_administrative_id:
        belongs = True
    else:
        belongs = child_administrative_id in get_administrative_level_descendants_using_mis(adl_db, parent_administrative_id, [])
    return belongs

def get_auto_increment_id(grm_db):
    try:
        max_auto_increment_id = grm_db.get_view_result('issues', 'auto_increment_id_stats')[0][0]['value']['max']
    except Exception:
        max_auto_increment_id = 0
    return max_auto_increment_id + 1


def get_administrative_level_descendants_using_mis(adl_db, parent_id, ids):
    from administrativelevels import models as administrativelevels_models
    data = []
    if parent_id:
        if int(parent_id) == 1:
            data = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(type="Region")
        else:
            data = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(parent_id=int(parent_id))
        
    descendants_ids = [obj.id for obj in data]
    for descendant_id in descendants_ids:
        get_administrative_level_descendants_using_mis(adl_db, descendant_id, ids)
        ids.append(str(descendant_id))

    return ids

def datetime_str(datetime_now = None):
    if not datetime_now:
        datetime_now = datetime.now()
        
    month = str(datetime_now.month) if datetime_now.month > 9 else ("0"+str(datetime_now.month))
    day = str(datetime_now.day) if datetime_now.day > 9 else ("0"+str(datetime_now.day))

    return f"{str(datetime_now.year)}-{month}-{str(day)} {str(datetime_now.hour)}:{str(datetime_now.minute)}:{str(datetime_now.second)}"