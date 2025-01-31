from django.contrib.auth.models import Group, Permission
from django.conf import settings
import requests
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


def create_facilitators_on_grm():
    couchdb_dbs_name = get_dbs_name()
    dbs_name = [db_name for db_name in couchdb_dbs_name if 'facilitator' in db_name]
    account_created = 0
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
                    if not User.objects.filter(email=doc_facilitator['email']).exists():
                        user = User()
                        user.email = doc_facilitator['email']
                        last_name = doc_facilitator['name'].split(' ')[0]
                        first_name = ' '.join(doc_facilitator['name'].split(' ')[1:])
                        user.first_name = first_name
                        user.last_name = last_name
                        user.phone_number = doc_facilitator['phone']

                        user.save()


                        print(f"{doc_facilitator['email']}. Okay")
                        account_created += 1

                        print(doc_facilitator)
                else:
                    nbr_skip += 1
        except Exception as exc:
            pass

    print()
    print(f"Account created : {account_created}")
    print(f"Skip : {nbr_skip}")
    
    
    
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
            set_user_government_worker_adl(user.governmentworker)
            