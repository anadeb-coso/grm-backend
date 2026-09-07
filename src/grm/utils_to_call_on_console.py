from django.contrib.auth.models import Group, Permission
from django.conf import settings
import requests
import time
from datetime import datetime, timedelta

from authentication.models import User, GovernmentWorker
from administrativelevels.models import AdministrativeLevel
from grm.call_objects_from_other_db import mis_objects_call
from authentication.utils import create_or_update_adl_user_adl, get_validation_code, set_user_government_worker_adl
from authentication.functions import send_code_by_mail
from client import get_db, get_dbs_name
from grm.my_librairies.functions import strip_accents


def create_training_user(start_number, end_number, administrative_level_type):
    """
    Ex: 
        create_training_user(0, 10, "Canton")
        create_training_user(7, 10, "Village")
    """

    administrative_level_filter_by_type = mis_objects_call.filter_objects(
        AdministrativeLevel, 
        type=administrative_level_type
    )

    if not administrative_level_filter_by_type.exists():
        print(f"Any administrative levels objects exists under type : {administrative_level_type}")
    else:
        print("Start saving")
        print()
        administrative_level_filter_by_type_values = administrative_level_filter_by_type.values_list('id')

        for number in range(start_number, end_number+1):
            email = f"training{number}.anadeb@gmail.com"
            first_name = f"training{number}"
            last_name = f"training{number}"
            phone_number = f"228{str(number) * 8}"
            if not User.objects.filter(email=email).exists():
                user = User()
                user.email = email
                user.first_name = first_name
                user.last_name = last_name
                user.phone_number = phone_number

                user.save()
                user = User.objects.get(email=email)

                government_worker = GovernmentWorker()

                government_worker.user = user
                government_worker.department = 1
                try:
                    adl_id = administrative_level_filter_by_type_values[number-1][0]
                except:
                    adl_id = administrative_level_filter_by_type_values[0][0]
                government_worker.administrative_id = adl_id

                government_worker.save()

                print(f"{email}. Okay")

        print()
        print("End saving")




def delete_training_user(start_number, end_number):
    """
    Ex: 
        delete_training_user(0, 10)
        delete_training_user(7, 10)
    """

    print("Start deleting")
    print()

    for number in range(start_number, end_number+1):
        email = f"training{number}.anadeb@gmail.com"

        users = User.objects.filter(email=email)
        if users.exists():
            user = users.first()
            user_id = user

            government_workers = GovernmentWorker.objects.filter(user_id=user_id)
            if government_workers.exists():
                government_worker = government_workers.first()
                government_worker.delete()
                
            user.delete()
            print(f"{email}. Okay")

    print()
    print("End deleting")


def delete_users(is_superuser=False):
    print("Start deleting")
    print()


    users = User.objects.filter(is_superuser=is_superuser)
    if users.exists():
        user = users.first()
        user_id = user

        government_workers = GovernmentWorker.objects.filter(user_id=user_id)
        if government_workers.exists():
            government_worker = government_workers.first()
            government_worker.delete()
            
        user.delete()
        print(f"{user.email}. Okay")

    print()
    print("End deleting")





def create_users_mis_on_grm(emails=[]):
    response = requests.get(f'{settings.BASE_URL_COSO_MIS}/api/users')
    if response.status_code == 200:
        # Parse the JSON data from the response
        users = response.json()
            
        account_created = 0
        account_updated = 0
        account_skiped = 0
        if not users:
            print(f"Any users objects exists")
        else:
            print("Start saving")
            print()

            for _user in users:
                if not emails or (emails and _user.get('email') in emails):
                    # not _user.get('is_superuser') and 
                    if _user.get('email') and \
                        not [\
                            _g for _g in _user['groups'] \
                                if _g['name'] in ['GeneralManager', 'Director', 'Advisor', 'Minister']\
                            ]:
                        
                        user = User.objects.filter(email=_user['email']).first()
                        if not user:
                            user = User()
                            user.email = _user['email']
                            user.first_name = _user['first_name']
                            user.last_name = _user['last_name']
                            user.phone_number = "22800000000"

                            user.save()
                            user = User.objects.get(email=_user['email'])


                            user.groups.set([])
                            user.user_permissions.set([])
                            for g in _user['groups']:
                                if Group.objects.filter(name=g['name']).exists():
                                    user.groups.add(Group.objects.get(name=g['name']))
                            for u_p in _user['user_permissions']:
                                if Permission.objects.filter(name=u_p['name']).exists():
                                    user.user_permissions.add(Permission.objects.get(name=u_p['name']))
                                
                            government_worker = GovernmentWorker()

                            government_worker.user = user
                            government_worker.department = 1
                            government_worker.administrative_id = "1"

                            government_worker.save()
                            user.save()
                            print(f"{_user['email']}. Okay")
                            account_created += 1
                        else:
                            user.groups.set([])
                            user.user_permissions.set([])
                            for g in _user['groups']:
                                if Group.objects.filter(name=g['name']).exists():
                                    user.groups.add(Group.objects.get(name=g['name']))
                            for u_p in _user['user_permissions']:
                                if Permission.objects.filter(name=u_p['name']).exists():
                                    user.user_permissions.add(Permission.objects.get(name=u_p['name']))

                            if not hasattr(user, 'governmentworker'):
                                government_worker = GovernmentWorker()
                                government_worker.user = user
                                government_worker.department = 1
                                government_worker.administrative_id = "1"

                                government_worker.save()
                            
                            account_updated += 1

                            user.save()
                else:
                    account_skiped += 1

            print()
            print(f"Account created : {account_created}")
            print(f"Account updated : {account_updated}")
            print(f"Account created : {account_skiped}")
            print()
            print("End saving")
    else:
        print("Error request!")


def create_facilitators_on_grm(project_name, emails=[]):
    response = requests.get(f'{settings.BASE_URL_COSO_MIS}/api/users')
    users_emails_mis = []
    if response.status_code == 200:
        users = response.json()
        users_emails_mis = [user['email'] for user in users if user.get('email')]

    couchdb_dbs_name = get_dbs_name()
    dbs_name = [db_name for db_name in couchdb_dbs_name if 'facilitator' in db_name]
    account_created = 0
    nbr_skip = 0
    account_updated = 0
    for db_name in dbs_name:
        facilitator_db = get_db(db_name)
        skip = False
        try:
            doc_facilitator = facilitator_db[facilitator_db.get_query_result({
                "type": "facilitator",
                "develop_mode": False,
                "training_mode": False,
                "sql_id": {
                    "$exists": True
                },
                "email": {
                    "$nin": users_emails_mis
                },
                # "total_number_of_tasks": {
                #     "$exists": True
                # },
                "sex": {
                    "$exists": True
                },
                # "geographical_units": {
                #     "$exists": True
                # }
                "$or": [
                    {
                        "total_number_of_tasks": {
                            "$exists": True
                        },
                        "geographical_units": {
                            "$exists": True
                        }
                    },
                    {
                        "facilitator_type": "technical_facilitator"
                    }
                ]
            })[0][0]["_id"]]

            if (not emails or (emails and doc_facilitator.get("email") in emails)) and (project_name in doc_facilitator.get("projects_names", []) and (doc_facilitator.get("geographical_units") or doc_facilitator.get("facilitator_type") == "technical_facilitator")):
                for _n in ['DAMTARE Tchably', 'LAMBONI Kitchéssoa', 'GOBINE Nimome']:
                    if strip_accents(_n) == strip_accents(doc_facilitator['name']):
                        skip = True
            
                if not skip:
                    user = User.objects.filter(email=doc_facilitator['email']).first()
                    if not user:
                        user = User()
                        user.email = doc_facilitator['email']
                        last_name = doc_facilitator['name'].split(' ')[0]
                        first_name = ' '.join(doc_facilitator['name'].split(' ')[1:])
                        user.first_name = first_name
                        user.last_name = last_name
                        user.phone_number = doc_facilitator['phone']
                        user.is_active = doc_facilitator['active']

                        user.save()


                        print(f"{doc_facilitator['email']}. Okay")
                        account_created += 1

                        print(doc_facilitator)
                    else:
                        user.is_active = doc_facilitator['active']
                        
                        user.groups.set([])

                        if doc_facilitator.get("facilitator_type") == "technical_facilitator":
                            for g in ["Facilitator", "TechnicalFacilitator"]:
                                if Group.objects.filter(name=g).exists():
                                    user.groups.add(Group.objects.get(name=g))
                        if doc_facilitator.get("facilitator_type") == "community_facilitator":
                            for g in ["Facilitator", "CommunityFacilitator"]:
                                if Group.objects.filter(name=g).exists():
                                    user.groups.add(Group.objects.get(name=g))
                        
                        account_updated += 1

                        user.save()
                else:
                    nbr_skip += 1
        except Exception as exc:
            pass

    print()
    print(f"Account created : {account_created}")
    print(f"Account updated : {account_updated}")
    print(f"Skip : {nbr_skip}")
    
    
def delete_facilitators_on_grm(project_name, emails=[]):
    couchdb_dbs_name = get_dbs_name()
    dbs_name = [db_name for db_name in couchdb_dbs_name if 'facilitator' in db_name]
    account_created = 0
    nbr_skip = 0
    account_updated = 0
    emails_deleted = []
    for db_name in dbs_name:
        facilitator_db = get_db(db_name)
        skip = False
        try:
            doc_facilitator = facilitator_db[facilitator_db.get_query_result({
                "type": "facilitator",
                "develop_mode": False,
                "training_mode": False,
                "sql_id": {
                    "$exists": True
                },
                # "total_number_of_tasks": {
                #     "$exists": True
                # },
                "sex": {
                    "$exists": True
                },
                # "geographical_units": {
                #     "$exists": True
                # }
                "$or": [
                    {
                        "total_number_of_tasks": {
                            "$exists": True
                        },
                        "geographical_units": {
                            "$exists": True
                        }
                    },
                    {
                        "facilitator_type": "technical_facilitator"
                    }
                ]
            })[0][0]["_id"]]

            if project_name in doc_facilitator.get("projects_names", []) and (not emails or doc_facilitator.get("email") in emails):
                emails_deleted.append(doc_facilitator['email'])
        except Exception as exc:
            pass
    
    if emails_deleted:
        if input(f"Do you want to delete facilitators with these emails : {emails_deleted} ? (y/n) ") == "y":
            User.objects.filter(email__in=emails_deleted).first().delete()
            print(f"Deleted facilitators: {emails_deleted}")


def delete_issues(text="testtest", start_date=None, end_date=None):
    grm_db = get_db('grm')
    
    selector = {
        "type": "issue",
        "description": {"$regex": f"^{text}"},
    }
    date_range = {}
    if start_date:
        start_date = datetime.strptime(start_date, '%d/%m/%Y').strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        date_range["$gte"] = start_date
        selector["intake_date"] = date_range
    if end_date:
        end_date = (datetime.strptime(end_date, '%d/%m/%Y') + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        date_range["$lte"] = end_date
        selector["intake_date"] = date_range
        
    resultats = grm_db.get_query_result(selector)
    _ = resultats[:].copy()
    for resultat in resultats:
        print(resultat.get('description'))
        grm_db[resultat.get('_id')].delete()
    
    return _



def send_facilitators_code():
    couchdb_dbs_name = get_dbs_name()
    dbs_name = [db_name for db_name in couchdb_dbs_name if 'facilitator' in db_name]
    nbr_mail_send = 0
    accounts_not_exist = 0
    nbr_skip = 0
    for db_name in dbs_name:
        facilitator_db = get_db(db_name)
        skip = False
        try:
            doc_facilitator = facilitator_db[facilitator_db.get_query_result({
                "type": "facilitator",
                "develop_mode": False,
                "training_mode": False,
                "sql_id": {
                    "$exists": True
                },
                "total_number_of_tasks": {
                    "$exists": True
                },
                "sex": {
                    "$exists": True
                },
                "geographical_units": {
                    "$exists": True
                }
            })[0][0]["_id"]]

            if doc_facilitator.get("geographical_units"):
                for _n in ['DAMTARE Tchably', 'LAMBONI Kitchéssoa', 'GOBINE Nimome']:
                    if strip_accents(_n) == strip_accents(doc_facilitator['name']):
                        skip = True
            
                if not skip:
                    users = User.objects.filter(email=doc_facilitator['email'])
                    if users.exists():
                        user = users.first()
                        send_code_by_mail(user, get_validation_code(user.email)) # Send user account code on their Email
                        nbr_mail_send += 1
                        print(doc_facilitator)
                    else:
                        accounts_not_exist += 1
                else:
                    nbr_skip += 1
        except Exception as exc:
            pass

    print()
    print(f"Mail send : {nbr_mail_send}")
    print(f"Accounts not exist : {accounts_not_exist}")
    print(f"Skip : {nbr_skip}")
    
    
def generate_user_adl_with_cvd():
    print("generate_user_adl_with_cvd")
    couchdb_dbs_name = get_dbs_name()
    dbs_name = [db_name for db_name in couchdb_dbs_name if 'facilitator' in db_name]
    nbr_success = 0
    accounts_not_exist = 0
    nbr_skip = 0
    for db_name in dbs_name:
        facilitator_db = get_db(db_name)
        skip = False
        try:
            doc_facilitator = facilitator_db[facilitator_db.get_query_result({
                "type": "facilitator",
                "develop_mode": False,
                "training_mode": False,
                "sql_id": {
                    "$exists": True
                },
                "total_number_of_tasks": {
                    "$exists": True
                },
                "sex": {
                    "$exists": True
                },
                "geographical_units": {
                    "$exists": True
                }
            })[0][0]["_id"]]
            
            if doc_facilitator.get("geographical_units"):
                for _n in ['DAMTARE Tchably', 'LAMBONI Kitchéssoa', 'GOBINE Nimome']:
                    if strip_accents(_n) == strip_accents(doc_facilitator['name']):
                        skip = True
            
                if not skip:
                    user_obj = User.objects.filter(email=doc_facilitator['email']).first()
                    if user_obj and hasattr(user_obj, 'governmentworker'):
                        
                        governmentworker = GovernmentWorker.objects.get(id=user_obj.governmentworker.id)

                        ids =  governmentworker.administrative_ids
                        if not ids:
                            ids = []
                        
                        """Search all villages with same cvd"""
                        all_adl_on_cvd = []
                        for _id in ids:
                            _obj = mis_objects_call.filter_objects(AdministrativeLevel, id=int(_id)).first()
                            if _obj and _obj.cvd:
                                for _village in _obj.cvd.get_villages():
                                    if str(_village.id) not in all_adl_on_cvd:
                                        all_adl_on_cvd.append(str(_village.id))
                            else:
                                all_adl_on_cvd.append(_id)
                                        
                        governmentworker.administrative_ids = list(set(all_adl_on_cvd))
                        governmentworker.save()
            
                        
                        nbr_success += 1
                        print(doc_facilitator)
                    else:
                        accounts_not_exist += 1
                else:
                    nbr_skip += 1
        except Exception as exc:
            print(exc)
            pass
        
    print()
    print(f"Success send : {nbr_success}")
    print(f"Accounts not exist : {accounts_not_exist}")
    print(f"Skip : {nbr_skip}")
    
    
    
def generate_adl_regions_objects():
    for user in User.objects.all():
        if user and hasattr(user, 'governmentworker') and user.governmentworker.administrative_id not in (None, '', '1', 1):
            print(user.email)
            set_user_government_worker_adl(user.governmentworker)
            time.sleep(5)


def encrypt_uncrypted_issues(category_ids=(4, 7), passwords=None, dry_run=False,
                             include_unconfirmed=False, include_files=True, limit=None):
    """Chiffre a posteriori les plaintes "sensibles" (catégories 4 et 7 par défaut) qui sont
    encore stockées en clair, en reproduisant exactement ce que fait l'enregistrement d'une
    plainte pour ces catégories (dashboard/grm/views.py::NewIssueConfirmFormView /
    UploadIssueAttachmentFormView) :

      1. `description` -> chiffrée avec le dernier mot de passe de la catégorie
         (`cryptography_fernet_encrypt(description, mot_de_passe_categorie)`), stockée sous la
         forme `str(b'gAAAA...')` — même format que la lecture attend (GetIssueDescriptionView).
      2. `citizen` -> chiffré dans `Pdata` (clé = mot de passe = `str(issue.pk)`), remplacé par "*".
      3. `contact_information.contact` -> chiffré dans `Cdata` (même clé), remplacé par "*"
         (mécanisme `authentication.models.anonymize_issue_data`).
      4. Pièces jointes (`Attachment` de l'issue, y compris celles portées par ses `Reason` /
         `EscalationReason`) -> contenu chiffré Fernet avec le mot de passe de la catégorie
         (`cryptography_fernet_encrypt(file, mot_de_passe_categorie, _type="file")`), fichier
         réécrit dans le storage et `file_name` préfixé `encrypt_` — même forme que la lecture
         attend (IssueAttachmentDecryptView, qui essaie `get_all_privacy_passwords`).

    Chaque élément est traité indépendamment et seulement s'il est encore en clair (pour les
    fichiers : non déchiffrables par un mot de passe connu de la catégorie) : la fonction est
    donc ré-exécutable sans risque de double chiffrement.

    Args:
        category_ids: `legacy_id` des catégories à traiter (défaut : 4 et 7).
        passwords: dict optionnel {legacy_id: "mot de passe en clair"} pour fournir/forcer le
            mot de passe de chiffrement (description ET fichiers) — utile si aucun mot de passe
            n'est enregistré dans l'app `privacy` pour la catégorie.
        dry_run: si True, n'écrit rien, affiche seulement ce qui serait modifié.
        include_unconfirmed: inclure aussi les brouillons (`confirmed=False`).
        include_files: chiffrer aussi les pièces jointes (défaut : True).
        limit: nombre maximum de plaintes à traiter (None = toutes).

    Ex :
        encrypt_uncrypted_issues()
        encrypt_uncrypted_issues(dry_run=True)
        encrypt_uncrypted_issues(category_ids=(4,), passwords={4: "monMotDePasse"})
        encrypt_uncrypted_issues(include_files=False)   # champs seulement
    """
    from django.core.files.base import ContentFile
    from django.utils import timezone

    from cryptography.fernet import Fernet

    from issue.models import Issue, Attachment, Reason, EscalationReason
    from authentication.models import Pdata, Cdata
    from grm.utils import cryptography_fernet_encrypt, cryptography_fernet_key
    from privacy.functions import get_all_privacy_passwords

    passwords = passwords or {}

    def _looks_encrypted(text):
        # Même heuristique que la lecture côté dashboard : un jeton Fernet est stocké sous la
        # forme `str(bytes)` -> commence par `b'` (et le corps base64 par `gAAAA`).
        return bool(text) and ("b'" in text or 'b"' in text)

    def _category_passwords_all(legacy_id):
        if legacy_id in passwords and passwords[legacy_id]:
            return [passwords[legacy_id]]
        return list(get_all_privacy_passwords(legacy_id))  # dernier mot de passe en tête

    def _category_password(legacy_id):
        all_passwords = _category_passwords_all(legacy_id)
        return all_passwords[0] if all_passwords else None

    def _issue_attachment_ids(issue):
        ids = set(issue.attachments.filter(is_deleted=False).values_list('pk', flat=True))
        ids |= set(
            Reason.objects.filter(issue=issue, attachment__isnull=False)
            .values_list('attachment_id', flat=True)
        )
        ids |= set(
            EscalationReason.objects.filter(issue=issue, attachment__isnull=False)
            .values_list('attachment_id', flat=True)
        )
        ids.discard(None)
        return ids

    def _encrypt_attachment(attachment, all_passwords, enc_password):
        """Retourne True si la pièce jointe a été (ou serait, en dry_run) chiffrée."""
        if not attachment.file:
            return False
        try:
            attachment.file.open('rb')
            raw = attachment.file.read()
        finally:
            try:
                attachment.file.close()
            except Exception:
                pass

        # Déjà chiffré ? (déchiffrable par un mot de passe connu de la catégorie)
        for pwd in all_passwords:
            try:
                Fernet(cryptography_fernet_key(pwd)).decrypt(raw)
                return False
            except Exception:
                continue

        if dry_run:
            return True

        token = Fernet(cryptography_fernet_key(enc_password)).encrypt(raw)
        new_name = (
            attachment.file_name if attachment.file_name and attachment.file_name.startswith('encrypt_')
            else f'encrypt_{attachment.file_name or attachment.pk}'
        )
        old_key = attachment.file.name
        attachment.file.save(new_name, ContentFile(token), save=False)
        attachment.file_name = new_name
        attachment.size = len(token)
        attachment.save(update_fields=['file', 'file_name', 'size', 'updated_at'])
        if old_key and old_key != attachment.file.name:
            try:
                attachment.file.storage.delete(old_key)
            except Exception:
                pass
        return True

    base_qs = Issue.objects.filter(
        category__legacy_id__in=list(category_ids), is_deleted=False,
    ).select_related('category').order_by('created_date')
    if not include_unconfirmed:
        base_qs = base_qs.filter(confirmed=True)
    if limit:
        base_qs = base_qs[:limit]

    stats = {
        'seen': 0, 'description': 0, 'citizen': 0, 'contact': 0, 'files': 0,
        'issues_changed': 0, 'skipped_no_password': 0, 'skipped_no_password_files': 0,
    }
    missing_password_categories = set()

    print(f"Start ({'DRY-RUN' if dry_run else 'APPLY'}) — catégories {tuple(category_ids)}")
    print()

    for issue in base_qs.iterator():
        stats['seen'] += 1
        key = str(issue.pk)
        legacy_id = issue.category.legacy_id if issue.category_id else None
        changed_fields = []
        files_done = 0

        # 1) description ----------------------------------------------------------------
        description = issue.description or ''
        if description and not _looks_encrypted(description):
            category_password = _category_password(legacy_id)
            if not category_password:
                stats['skipped_no_password'] += 1
                missing_password_categories.add(legacy_id)
            else:
                if not dry_run:
                    issue.description = str(cryptography_fernet_encrypt(description, category_password))
                changed_fields.append('description')
                stats['description'] += 1

        # 2) citizen -> Pdata ---------------------------------------------------------
        if issue.citizen and issue.citizen != '*':
            if not dry_run:
                pdata, _ = Pdata.objects.get_or_create(key=key)
                pdata.data = cryptography_fernet_encrypt(issue.citizen, key)
                pdata.save()
                issue.citizen = '*'
            changed_fields.append('citizen')
            stats['citizen'] += 1

        # 3) contact_information.contact -> Cdata ------------------------------------
        contact_information = issue.contact_information_value
        if isinstance(contact_information, dict) and contact_information.get('contact') \
                and contact_information.get('contact') != '*':
            if not dry_run:
                cdata, _ = Cdata.objects.get_or_create(key=key)
                cdata.data = cryptography_fernet_encrypt(contact_information['contact'], key)
                cdata.save()
                issue.contact_information = {
                    'type': contact_information.get('type'),
                    'contact': '*',
                }
            changed_fields.append('contact_information')
            stats['contact'] += 1

        if changed_fields:
            stats['issues_changed'] += 1
            if not dry_run:
                # `updated_at` explicite pour que la modification remonte au pull incrémental
                # mobile (auto_now n'est pas appliqué par save(update_fields=...) sans lui).
                issue.save(update_fields=changed_fields + ['updated_at'])

        # 4) pièces jointes ---------------------------------------------------------
        if include_files:
            attachment_ids = _issue_attachment_ids(issue)
            if attachment_ids:
                all_passwords = _category_passwords_all(legacy_id)
                enc_password = all_passwords[0] if all_passwords else None
                if not enc_password:
                    stats['skipped_no_password_files'] += len(attachment_ids)
                    missing_password_categories.add(legacy_id)
                else:
                    for attachment in Attachment.objects.filter(pk__in=attachment_ids):
                        try:
                            if _encrypt_attachment(attachment, all_passwords, enc_password):
                                files_done += 1
                        except Exception as exc:
                            print(f"  ! {issue.internal_code or issue.pk} — pièce jointe "
                                  f"{attachment.pk} : {exc}")
            if files_done:
                stats['files'] += files_done

        if changed_fields or files_done:
            details = list(changed_fields)
            if files_done:
                details.append(f"{files_done} fichier(s)")
            print(f"{issue.internal_code or issue.pk} (cat {legacy_id}) : {', '.join(details)}")

    print()
    print(f"Plaintes examinées         : {stats['seen']}")
    print(f"Plaintes modifiées         : {stats['issues_changed']}")
    print(f"  - description chiffrée    : {stats['description']}")
    print(f"  - citizen anonymisé       : {stats['citizen']}")
    print(f"  - contact anonymisé       : {stats['contact']}")
    print(f"  - pièces jointes chiffrées: {stats['files']}")
    if stats['skipped_no_password'] or stats['skipped_no_password_files']:
        cats = sorted(c for c in missing_password_categories if c is not None)
        print(f"Non chiffré, aucun mot de passe pour catégorie(s) {cats} : "
              f"{stats['skipped_no_password']} description(s), "
              f"{stats['skipped_no_password_files']} fichier(s)")
    print("End" + (" (DRY-RUN, rien écrit)" if dry_run else ""))
    return stats
