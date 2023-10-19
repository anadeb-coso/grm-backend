from authentication.models import User, GovernmentWorker
from administrativelevels.models import AdministrativeLevel
from grm.call_objects_from_other_db import mis_objects_call
from authentication.utils import create_or_update_adl_user_adl


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