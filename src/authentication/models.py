import os

# import cryptocode
# from hashlib import scrypt
import shortuuid as uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save, post_delete, pre_delete
from django.db.models import Count, Q

from grm.utils import (
    get_parent_administrative_level_using_mis, get_related_region_with_specific_level_using_mis,
    sort_dictionary_list_by_field, belongs_to_region_using_mis, cryptography_fernet_encrypt
)
from grm.models_base import safe_json_value
from authentication.utils import (create_or_update_adl_user_adl, delete_adl_user_adl, 
                                  set_user_government_worker_adl, delete_user_government_worker_adl)
from administrativelevels.models import AdministrativeLevel
from grm.call_objects_from_other_db import mis_objects_call
from issue.models import Issue, Adl

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
    administrative_ids = models.JSONField(blank=True, null=True, verbose_name=_('administrative levels'))
    additional_administrative_ids = models.JSONField(blank=True, null=True, verbose_name=_('Additional administrative levels'))

    class Meta:
        verbose_name = _('Government Worker')
        verbose_name_plural = _('Government Workers')

    @property
    def name(self):
        return self.user.name

    # Accesseurs "sûrs" : ces deux colonnes gouvernent le périmètre d'accès aux issues
    # (has_read_permission_for_issue/all_administrative_ids ci-dessous) — si jamais stockées
    # double-encodées (chaîne JSON au lieu de liste, cf. grm.models_base.safe_json_value, même
    # défaut déjà observé sur Issue.location_info et consorts pour les issues `source='mobile'`),
    # une comparaison `in`/concaténation de liste échouerait silencieusement et bloquerait l'accès
    # au lieu de lever une erreur visible.
    @property
    def administrative_ids_value(self):
        return safe_json_value(self.administrative_ids)

    @property
    def additional_administrative_ids_value(self):
        return safe_json_value(self.additional_administrative_ids)

    def has_read_permission_for_issue(self, issue):
        """`issue` est une instance `Issue` Postgres (`issue.models.Issue`). Anciennement
        paramétrée par un handle CouchDB `adl_db` (mort/inutilisé dans le corps de la fonction, cf.
        migration du dashboard web) et un dict de document brut."""
        try:
            issue_administrative_id = str(issue.administrative_region_id)
            if issue_administrative_id != self.administrative_id:
                assigned_department = issue.category.assigned_department_value
                issue_department_id = (
                    assigned_department.get('id') if isinstance(assigned_department, dict)
                    else assigned_department
                )
                if self.department != issue_department_id:
                    return False
            for _id in self.all_administrative_ids:
                belongs = belongs_to_region_using_mis(None, issue_administrative_id, _id, self.user)
                if belongs:
                    return belongs

        except Exception:
            pass
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
    
    @property
    def all_administrative_ids(self):
        # Bug pré-existant corrigé ici : un `+` manquant entre les deux derniers termes rendait
        # cette propriété inutilisable (`TypeError: 'list' object is not callable`) dès qu'elle
        # était appelée — découvert lors de la migration de `has_read_permission_for_issue`.
        administrative_ids = self.administrative_ids_value
        additional_administrative_ids = self.additional_administrative_ids_value
        return list(
                set(
                    (administrative_ids if administrative_ids else list()) \
                    + ([self.administrative_id] if self.administrative_id else list()) \
                    + (additional_administrative_ids if additional_administrative_ids else list())
                )
            )


def get_government_worker_choices(empty_choice=True):
    query = GovernmentWorker.objects.select_related('user')
    choices = [(i.user.id, f'{i.user.first_name} {i.user.last_name}') for i in query]
    if empty_choice:
        choices = [('', '')] + choices
    return choices


def get_assignee(issue, errors=None):
    """Détermine automatiquement l'agent à assigner à une `Issue` (instance Postgres) nouvellement
    créée, en fonction de sa catégorie/département/niveau administratif. Remplace l'ancienne
    version CouchDB (`grm_db`/`eadl_db`/`adl_db`, requêtes Mango + vue `issues/group_by_assignee`)
    — opère directement sur les instances Postgres `Issue`/`IssueCategory`/`IssueDepartment`/
    `GovernmentWorker`/`Adl`, ce qui élimine le besoin d'aller chercher la catégorie/le
    département par requête séparée (déjà accessibles via les FK)."""
    from issue.models import Adl, IssueDepartment

    category = issue.category
    assigned_department = category.assigned_department or {}
    department_id = (
        assigned_department.get('id') if isinstance(assigned_department, dict)
        else assigned_department
    )

    assignee = None

    if category.confidentiality_level != 'Very_sensitive' and issue.reporter_id:
        # Assigne les plaintes non sensibles à la personne qui les a enregistrées.
        assignee = {"id": issue.reporter_id, "name": issue.reporter_name}

    elif category.redirection_protocol:
        assigned_department_level = (
            assigned_department.get('administrative_level') if isinstance(assigned_department, dict) else None
        )
        assigned_department_level = assigned_department_level.strip() if assigned_department_level else None
        administrative_id = None

        if not assigned_department_level:
            try:
                reporter = GovernmentWorker.objects.get(user_id=issue.reporter_id)
                administrative_id = reporter.administrative_id
            except GovernmentWorker.DoesNotExist:
                pass

        if not administrative_id:
            level = category.administrative_level
            related_region = get_related_region_with_specific_level_using_mis(
                issue.administrative_region_id, level,
            )
            if related_region is None:
                if errors:
                    errors.append('Error trying to resolve administrative level in get_assignee function')
                return None
            administrative_id = related_region['administrative_id']

        related_workers = set(
            GovernmentWorker.objects.filter(
                Q(administrative_ids__contains=[administrative_id]) | Q(administrative_id=administrative_id),
                department=department_id,
                ).values_list('user_id', flat=True))
        if not related_workers:
            related_workers = set(
                Adl.objects.filter(
                Q(administrative_region_ids__contains=[administrative_id]) | Q(smallest_administrative_level_ids__contains=[administrative_id])
                ).values_list('representative__id', flat=True))

        # Équivalent de l'ancienne vue CouchDB `issues/group_by_assignee` (group=True) : nombre
        # d'issues déjà assignées, par agent, dans ce département — sert à équilibrer la charge.
        assignments_result = list(
            Issue.objects.filter(
                assignee__isnull=False, category__assigned_department__id=department_id, is_deleted=False,
            )
            .values('assignee_id', 'assignee_name')
            .annotate(value=Count('id'))
        )

        department_workers_with_assignment = {a['assignee_id'] for a in assignments_result}
        department_workers_without_assignment = related_workers - department_workers_with_assignment

        if department_workers_without_assignment:
            worker_id = list(department_workers_without_assignment)[0]
            worker_without_assignment = GovernmentWorker.objects.get(user_id=worker_id)
            assignee = {
                "id": worker_id,
                "name": worker_without_assignment.name
            }
        else:
            assignee = ""
            if assignments_result:
                assignments_result = sort_dictionary_list_by_field(assignments_result, 'value')
                for assignment in assignments_result:
                    worker_id = assignment['assignee_id']
                    if worker_id in related_workers:
                        assignee = {
                            "id": worker_id,
                            "name": assignment['assignee_name']
                        }
                        break
            elif related_workers:
                worker = GovernmentWorker.objects.filter(
                    Q(administrative_ids__contains=[administrative_id]) | Q(administrative_id=administrative_id),
                    department=department_id,
                    ).first()
                if not worker:
                    _adl = Adl.objects.filter(
                        Q(administrative_region_ids__contains=[administrative_id]) | Q(smallest_administrative_level_ids__contains=[administrative_id])
                    ).first()
                    worker = GovernmentWorker.objects.filter(
                        user=_adl.representative
                    )
                if worker:
                    assignee = {
                        "id": worker.user.id,
                        "name": worker.name
                    }
    else:
        try:
            department = IssueDepartment.objects.get(legacy_id=department_id)
        except IssueDepartment.DoesNotExist:
            if errors:
                errors.append('Error trying to get issue_department in get_assignee function')
            raise
        assignee = {"id": department.head_id, "name": department.head_name} if department.head_id else None

    if not assignee:
        # Dernier recours : le secrétaire du village concerné (Adl.village_secretary=True).
        village_secretary = Adl.objects.filter(
            Q(administrative_region_ids__contains=[issue.administrative_region_id]) | Q(smallest_administrative_level_ids__contains=[issue.administrative_region_id]),
            village_secretary=True,
        ).first()
        if village_secretary and village_secretary.representative_id:
            assignee = {
                "id": village_secretary.representative_id,
                "name": village_secretary.representative_name,
            }

    if not assignee:
        # Une dernière tentative : un utilisateur ayant un groupe `Privacy` ou `Safeguard`
        privacy_or_safeguard_user = User.objects.filter(
            Q(groups__name='Privacy') | Q(groups__name='Safeguard')
        ).order_by('groups__name', 'id').first()
        if privacy_or_safeguard_user:
            assignee = {
                "id": privacy_or_safeguard_user.id,
                "name": privacy_or_safeguard_user.name,
            }
    
    return assignee


def get_assignee_to_escalate(department_id, administrative_id):
    """Remplace l'ancienne version CouchDB (paramètre `adl_db` retiré, plus nécessaire) —
    `get_parent_administrative_level_using_mis` interroge directement la base `mis`."""
    parent = get_parent_administrative_level_using_mis(administrative_id)
    if parent:

        administrative_id = parent['administrative_id']
        parent_obj = mis_objects_call.filter_objects(AdministrativeLevel, id=administrative_id).first()

        if parent['administrative_level'] == 'Commune' or \
            (parent['administrative_level'] == 'Region' and parent_obj and parent_obj.name.upper() in ('KARA', 'CENTRALE')) or \
            (parent['administrative_level'] == 'Prefecture' and parent_obj and parent_obj.parent and parent_obj.parent.name.upper() == 'SAVANES'): #Specially for COSO TOGO

            return get_assignee_to_escalate(department_id, administrative_id)

        else:
            worker = GovernmentWorker.objects.filter(
                Q(administrative_ids__contains=[administrative_id]) | Q(administrative_id=administrative_id),
                department=department_id
                ).first()
            if not worker:
                _adl = Adl.objects.filter(
                    Q(administrative_region_ids__contains=[administrative_id]) | Q(smallest_administrative_level_ids__contains=[administrative_id])
                ).first()
                worker = GovernmentWorker.objects.filter(
                    user=_adl.representative
                )
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
    return None, None

def get_adl_to_escalate(administrative_id):
    """Remplace l'ancienne version CouchDB (paramètre `adl_db` retiré, plus nécessaire)."""
    parent = get_parent_administrative_level_using_mis(administrative_id)
    current_adl = mis_objects_call.filter_objects(AdministrativeLevel, id=administrative_id).first()
    if parent:

        administrative_id = parent['administrative_id']
        parent_obj = mis_objects_call.filter_objects(AdministrativeLevel, id=administrative_id).first()
        current_adl = parent_obj

        if parent['administrative_level'] == 'Commune' or \
            (parent['administrative_level'] == 'Region' and parent_obj and parent_obj.name.upper() in ('KARA', 'CENTRALE')) or \
            (parent['administrative_level'] == 'Prefecture' and parent_obj and parent_obj.parent and parent_obj.parent.name.upper() == 'SAVANES'): #Specially for COSO TOGO

            return get_adl_to_escalate(administrative_id)

        else:
            return {
                "administrative_id": parent['administrative_id'],
                "name": parent['name'],
                "administrative_level": parent['administrative_level']
            }
        
    if not parent and current_adl.type == 'Region': #Specially for COSO TOGO
        return {
            "administrative_id": "1",
            "name": "TOGO",
            "administrative_level": "Country"
        }

    return None


def get_cvgp_member_escalation_replacement_assignee(administrative_id):
    """Détermine à qui réassigner une issue qui vient de quitter le niveau Village pour le niveau
    supérieur (Canton) alors qu'elle était suivie par un membre du groupe `CVGPMembers` — ce
    dernier perd la main dessus dès que l'issue est remontée (cf.
    `grm-frontend/.../IssueActions/containers/Content.js::actionsDisabledForCvgp`, qui désactive
    déjà les boutons d'action côté mobile pour ce même profil une fois le niveau Village quitté).
    Ordre de repli demandé :
      1. Un `CommunityFacilitator` actif couvrant le village de l'issue (même patron de requête
         que le filtre gabarit `dashboard/templatetags/custom_tags.py::get_adl_by_adm_id`).
      2. À défaut, un `Supervisor` actif couvrant ce même village.
      3. À défaut, un `Safeguard` actif — rôle national, sans notion de village (même repli que
         `get_assignee` ci-dessus pour les groupes `Privacy`/`Safeguard`).
    Retourne l'instance `User` choisie, ou `None` si personne n'est disponible."""
    administrative_id = str(administrative_id)

    for group_name in ('CommunityFacilitator', 'Supervisor'):
        adl = Adl.objects.select_related('representative').filter(
            Q(administrative_region_ids__contains=[administrative_id])
            | Q(smallest_administrative_level_ids__contains=[administrative_id]),
            is_deleted=False, representative__isnull=False, representative__is_active=True,
            representative__groups__name=group_name,
        ).first()
        if adl and adl.representative_id:
            return adl.representative

    return User.objects.filter(groups__name='Safeguard', is_active=True).order_by('id').first()


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

pre_delete.connect(delete_user, sender=User)  # pre_delete : le cascade SET_NULL sur Adl.representative
                                               # doit encore pointer sur ce user au moment du lookup
                                               # (post_delete arriverait trop tard, cf. authentication/utils.py)
post_save.connect(create_or_update_user, sender=User)
post_save.connect(set_user_government_worker, sender=GovernmentWorker)
post_delete.connect(delete_user_government_worker, sender=GovernmentWorker)
