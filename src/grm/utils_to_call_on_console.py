from django.contrib.auth.models import Group, Permission
from django.conf import settings
import requests

from authentication.models import User, GovernmentWorker
from administrativelevels.models import AdministrativeLevel
from grm.call_objects_from_other_db import mis_objects_call
from authentication.utils import create_or_update_adl_user_adl
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





def create_users_mis_on_grm():
    response = requests.get(f'{settings.BASE_URL_COSO_MIS}/api/users')
    if response.status_code == 200:
        # Parse the JSON data from the response
        users = response.json()
            
        account_created = 0
        if not users:
            print(f"Any users objects exists")
        else:
            print("Start saving")
            print()

            for _user in users:
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
                            
                        user.save()


            print()
            print(f"Account created : {account_created}")
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