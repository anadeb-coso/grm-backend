import os

# import cryptocode
# from hashlib import scrypt
import shortuuid as uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save, post_delete

from grm.utils import (
    belongs_to_region, get_parent_administrative_level, get_related_region_with_specific_level,
    sort_dictionary_list_by_field, belongs_to_region_using_mis, cryptography_fernet_encrypt
)
from authentication.utils import (create_or_update_adl_user_adl, delete_adl_user_adl, 
                                  set_user_government_worker_adl, delete_user_government_worker_adl)
from administrativelevels.models import AdministrativeLevel
from grm.call_objects_from_other_db import mis_objects_call

def photo_path(instance, filename):
    filename, file_extension = os.path.splitext(filename)
    filename = '{}{}'.format(uuid.uuid(), file_extension)
    return 'photos/{}'.format(filename)


class User(AbstractUser):
    email = models.EmailField(unique=True, verbose_name=_('email address'))
    phone_number = models.CharField(max_length=45, verbose_name=_('phone number'))
    photo = models.ImageField(upload_to=photo_path, blank=True, null=True, verbose_name=_('photo'))

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        if not self.username:
            self.username = str(uuid.uuid())
        return super().save(*args, **kwargs)

    @property
    def name(self):
        return f'{self.first_name} {self.last_name}'
    
    @property
    def administrative_level(self):
        if self and hasattr(self, 'governmentworker'):
            return self.governmentworker.administrative_level
        return None


class AbstractKeyData(models.Model):
    key = models.CharField(max_length=255, primary_key=True, unique=True)
    data = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        abstract = True


class Pdata(AbstractKeyData):
    class Meta:
        verbose_name_plural = 'Pdata'

    def __str__(self):
        return f'{self.key}: {self.data}'


class Cdata(AbstractKeyData):
    class Meta:
        verbose_name_plural = 'Cdata'

    def __str__(self):
        return f'{self.key}: {self.data}'


class GovernmentWorker(models.Model):
    user = models.OneToOneField('User', models.PROTECT)
    department = models.PositiveSmallIntegerField(db_index=True, verbose_name=_('department'))
    administrative_id = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_('administrative level'))

    class Meta:
        verbose_name = _('Government Worker')
        verbose_name_plural = _('Government Workers')

    @property
    def name(self):
        return self.user.name

    def has_read_permission_for_issue(self, adl_db, issue):
        try:
            issue_administrative_id = issue['administrative_region']['administrative_id']
            if issue_administrative_id != self.administrative_id:
                issue_department_id = issue['category']['assigned_department']
                if self.department != issue_department_id:
                    return False
            # belongs = belongs_to_region(adl_db, issue_administrative_id, self.administrative_id)
            belongs = belongs_to_region_using_mis(adl_db, issue_administrative_id, self.administrative_id, self.user)
            return belongs
        except Exception:
            return False
    
    def administrative_level(self):
        if self.administrative_id == "1":
            a = AdministrativeLevel()
            a.name = "TOGO"
            a.type = _("Country").__str__()
            return a
        try:
            return AdministrativeLevel.objects.using('mis').get(id=int(self.administrative_id))
        except AdministrativeLevel.DoesNotExist as e:
            return None
        except Exception as exc:
            print(exc)
            return None


def get_government_worker_choices(empty_choice=True):
    query = GovernmentWorker.objects.select_related('user')
    choices = [(i.user.id, f'{i.user.first_name} {i.user.last_name}') for i in query]
    if empty_choice:
        choices = [('', '')] + choices
    return choices


def get_assignee(grm_db, eadl_db, adl_db, issue_doc, errors=None):
    try:
        doc_category = grm_db.get_query_result({
            "id": issue_doc['category']['id'],
            "type": 'issue_category'
        })[0][0]
    except Exception:
        if errors:
            error = 'Error trying to get issue_category document in get_assignee function'
            errors.append(error)
        raise

    assigned_department = doc_category['assigned_department']
    department_id = assigned_department['id']

    if doc_category['redirection_protocol']:
        assigned_department_level = assigned_department[
            'administrative_level'] if 'administrative_level' in assigned_department else None
        assigned_department_level = assigned_department_level.strip() if assigned_department_level else None
        administrative_id = None

        if not assigned_department_level:
            try:
                reporter = GovernmentWorker.objects.get(user=issue_doc['reporter']['id'])
                administrative_id = reporter.administrative_id
            except Exception:
                pass

        if not administrative_id:
            try:
                doc_administrative_level = adl_db.get_query_result({
                    "administrative_id": issue_doc['administrative_region']['administrative_id'],
                    "type": 'administrative_level'
                })[0][0]
            except Exception:
                if errors:
                    error = 'Error trying to get administrative_level document in get_assignee function'
                    errors.append(error)
                raise
            level = issue_doc['category']['administrative_level']
            related_region = get_related_region_with_specific_level(adl_db, doc_administrative_level, level)
            administrative_id = related_region['administrative_id']

        related_workers = set(
            GovernmentWorker.objects.filter(
                department=department_id, administrative_id=administrative_id).values_list('user', flat=True))

        startkey = [department_id, None, None]
        endkey = [department_id, {}, {}]
        assignments_result = grm_db.get_view_result(
            'issues', 'group_by_assignee', group=True, startkey=startkey, endkey=endkey)
        assignments_result = [doc for doc in assignments_result]

        department_workers_with_assignment = {worker['key'][1] for worker in assignments_result}
        department_workers_without_assignment = related_workers - department_workers_with_assignment

        if department_workers_without_assignment:
            worker_id = list(department_workers_without_assignment)[0]
            worker_without_assignment = GovernmentWorker.objects.get(user=worker_id)
            assignee = {
                "id": worker_id,
                "name": worker_without_assignment.name
            }
        else:
            assignee = ""
            if assignments_result:
                assignments_result = sort_dictionary_list_by_field(assignments_result, 'value')
                for assignment in assignments_result:
                    worker_id = assignment['key'][1]
                    if worker_id in related_workers:
                        assignee = {
                            "id": worker_id,
                            "name": assignment['key'][2]
                        }
                        break
            elif related_workers:
                worker = GovernmentWorker.objects.filter(
                    department=department_id, administrative_id=administrative_id).first()
                assignee = {
                    "id": worker.user.id,
                    "name": worker.name
                }
    else:
        try:
            doc_department = grm_db.get_query_result({
                "id": department_id,
                "type": 'issue_department'
            })[0][0]
        except Exception:
            if errors:
                error = 'Error trying to get issue_department document in get_assignee function'
                errors.append(error)
            raise
        assignee = doc_department['head']
    if not assignee:
        try:
            adl_user = eadl_db.get_query_result({
                "administrative_level": issue_doc['category']['administrative_level'],
                "administrative_region": issue_doc['administrative_region']['administrative_id'],
                "village_secretary": 1,
                "type": 'adl'
            })[0][0]
            assignee = {
                "id": adl_user['_id'],
                "name": adl_user['representative']['name']
            }
        except Exception:
            pass
    return assignee


def get_assignee_to_escalate(adl_db, department_id, administrative_id):
    try:
        parent = get_parent_administrative_level(adl_db, administrative_id)
    except Exception:
        raise
    if parent:
        
        administrative_id = parent['administrative_id']
        parent_obj = mis_objects_call.filter_objects(AdministrativeLevel, id=administrative_id).first()
        
        if parent['administrative_level'] == 'Commune' or \
            (parent['administrative_level'] == 'Region' and parent_obj and parent_obj.name.upper() in ('KARA', 'CENTRALE')) or \
            (parent['administrative_level'] == 'Prefecture' and parent_obj and parent_obj.parent and parent_obj.parent.name.upper() == 'SAVANES'): #Specially for COSO TOGO
        
            return get_assignee_to_escalate(adl_db, department_id, administrative_id)
        
        else:
            worker = GovernmentWorker.objects.filter(department=department_id, administrative_id=administrative_id).first()
            if worker:
                assignee = {
                    "id": worker.user.id,
                    "name": worker.name
                }
                return assignee, {
                    "administrative_id": parent['administrative_id'],
                    "name": parent['name'],
                    "administrative_level": parent['administrative_level']
                }
        # return get_assignee_to_escalate(adl_db, department_id, administrative_id)
    return None, None


def anonymize_issue_data(issue_doc):
    key = issue_doc['_id']
    citizen = issue_doc['citizen']
    if citizen:
        pdata, _ = Pdata.objects.get_or_create(key=key)
        # data_encoded = cryptocode.encrypt(citizen, key)
        data_encoded = cryptography_fernet_encrypt(citizen, key)
        
        pdata.data = data_encoded
        pdata.save()
        issue_doc['citizen'] = "*"
    else:
        Pdata.objects.filter(key=key).delete()

    contact_information = issue_doc['contact_information']
    if contact_information:
        contact = contact_information['contact']
        cdata, _ = Cdata.objects.get_or_create(key=key)
        # data_encoded = cryptocode.encrypt(contact, key)
        data_encoded = cryptography_fernet_encrypt(contact, key)
        cdata.data = data_encoded
        cdata.save()
        issue_doc['contact_information'] = {
            "type": contact_information['type'],
            "contact": "*",
        }
    else:
        Cdata.objects.filter(key=key).delete()




def create_or_update_user(sender, instance, **kwargs):
    # if kwargs['created']:
    print(kwargs['created'])
    try:
        create_or_update_adl_user_adl(instance, False if kwargs['created'] else True)
    except Exception as exc:
        print(exc)

def delete_user(sender, instance, **kwargs):
    try:
        delete_adl_user_adl(instance)
    except Exception as exc:
        print(exc)

def set_user_government_worker(sender, instance, **kwargs):
    # if kwargs['created']:
    try:
        set_user_government_worker_adl(instance)
    except Exception as exc:
        print(exc)

def delete_user_government_worker(sender, instance, **kwargs):
    # if kwargs['created']:
    try:
        delete_user_government_worker_adl(instance)
    except Exception as exc:
        print(exc)

post_delete.connect(delete_user, sender=User)
post_save.connect(create_or_update_user, sender=User)
post_save.connect(set_user_government_worker, sender=GovernmentWorker)
post_delete.connect(delete_user_government_worker, sender=GovernmentWorker)
