from datetime import datetime
from django.conf import settings
from django.utils.translation import gettext_lazy

from django import template

from authentication.utils import get_validation_code
from client import get_db
from dashboard.grm import CITIZEN_TYPE_CHOICES, CITIZEN_TYPE_CHOICES_ALT, CONTACT_CHOICES, MEDIUM_CHOICES
from grm.utils import get_administrative_region_name as get_region_name

register = template.Library()

COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL = settings.COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL

@register.filter
def get(dictionary, key):
    return dictionary.get(key, None)


@register.simple_tag
def get_code(email):
    code = "-"
    if email:
        code = get_validation_code(email)
    return code


@register.simple_tag
def get_status_phase(tasks):
    len_tasks = len(tasks)
    status = 'in-progress'
    completed = len([task for task in tasks if task['status'] == 'completed'])
    not_started = len([task for task in tasks if task['status'] == 'not-started'])
    if completed == len_tasks:
        status = 'completed'
    elif not_started == len_tasks:
        status = 'not-started'
    return status


@register.simple_tag
def get_completed_tasks(tasks):
    len_tasks = len(tasks)
    completed = len([task for task in tasks if task['status'] == 'completed'])
    return f'{completed}/{len_tasks}'


@register.simple_tag
def date_order_format(date):
    data = date.split('-') if date else []
    return f'{data[2]}{data[1]}{data[0]}' if len(data) > 2 else ''


@register.simple_tag
def get_date(date_time):
    data = date_time.split('T') if date_time else ''
    if data:
        data = data[0].split('-')
        data = f'{data[2]}-{data[1]}-{data[0]}' if len(data) > 2 else ''
    return data


@register.filter(expects_localtime=True)
def string_to_date(date_time, date_format="%Y-%m-%dT%H:%M:%S.%fZ"):
    if date_time:
        return datetime.strptime(date_time, date_format)


@register.simple_tag
def get_days_until_today(date_time):
    date = datetime.strptime(date_time, '%Y-%m-%dT%H:%M:%S.%fZ')
    delta = datetime.now() - date
    return delta.days


@register.simple_tag
def get_days_until_date(date_time):
    date = datetime.strptime(date_time, '%Y-%m-%dT%H:%M:%S.%fZ')
    delta = date - datetime.now()
    return delta.days


@register.simple_tag
def get_percentage_style(percentage):
    style = 'danger'
    percentage = int(percentage)
    if percentage > 19:
        style = 'yellow'
    if percentage > 49:
        style = 'primary'
    return style


@register.filter
def next_in_circular_list(items, i):
    if i >= len(items):
        i %= len(items)
    return items[i]


@register.simple_tag
def get_citizen_type_display(value):
    for key, label in CITIZEN_TYPE_CHOICES:
        if key == value:
            return label


@register.simple_tag
def get_citizen_type_alt_display(value):
    for key, label in CITIZEN_TYPE_CHOICES_ALT:
        if key == value:
            return label


@register.simple_tag
def get_contact_type_display(value):
    for key, label in CONTACT_CHOICES:
        if key == value:
            return label


@register.simple_tag
def get_contact_medium_display(value):
    for key, label in MEDIUM_CHOICES:
        if key == value:
            return label


@register.simple_tag
def get_initials(string):
    return ''.join((w[0] for w in string.split(' ') if w)).upper()


@register.simple_tag
def get_hour(date_time):
    data = date_time.split('T') if date_time else ''
    if data:
        data = data[1].split('.')[0]
    return data


@register.simple_tag
def get_administrative_region_name(administrative_id):
    adl_db = get_db(COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL)
    return get_region_name(adl_db, administrative_id)



@register.filter(name='has_group') 
def has_group(user, group_name):
    return user.groups.filter(name=group_name).exists() 

@register.filter(name='has_perm') 
def has_perm(user, perm_name):
    return user.user_permissions.filter(name=perm_name).exists() 

@register.filter(name='has_per') 
def has_per(user):
    return user.user_permissions

@register.filter(name='get_group_high') 
def get_group_high(user):
    """
    All Groups permissions
        - SuperAdmin            : 
        - CDD Specialist        : CDDSpecialist
        - Admin                 : Admin
        - Evaluator             : Evaluator
        - Accountant            : Accountant
        - Regional Coordinator  : RegionalCoordinator
        - National Coordinator  : NationalCoordinator
        - General Manager  : GeneralManager
        - Director  : Director
        - Advisor  : Advisor
        - Minister  : Minister
    """
    if user.is_superuser:
        return gettext_lazy("Principal Administrator").__str__()
    
    if user.groups.filter(name="Admin").exists():
        return gettext_lazy("Administrator").__str__()
    if user.groups.filter(name="CDDSpecialist").exists():
        return gettext_lazy("CDD Specialist").__str__()
    if user.groups.filter(name="Evaluator").exists():
        return gettext_lazy("Evaluator").__str__()
    if user.groups.filter(name="Accountant").exists():
        return gettext_lazy("Accountant").__str__()
    if user.groups.filter(name="RegionalCoordinator").exists():
        return gettext_lazy("Regional Coordinator").__str__()
    if user.groups.filter(name="NationalCoordinator").exists():
        return gettext_lazy("National Coordinator").__str__()
    if user.groups.filter(name="GeneralManager").exists():
        return gettext_lazy("General Manager").__str__()
    if user.groups.filter(name="Director").exists():
        return gettext_lazy("Director").__str__()
    if user.groups.filter(name="Advisor").exists():
        return gettext_lazy("Advisor").__str__()
    if user.groups.filter(name="Minister").exists():
        return gettext_lazy("Minister").__str__()


    return gettext_lazy("User").__str__()