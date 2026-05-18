import os
from datetime import datetime
from sys import platform
import math
from django.utils.translation import gettext_lazy as _

from administrativelevels.models import AdministrativeLevel
from grm.call_objects_from_other_db import mis_objects_call
from authentication.models import User, GovernmentWorker

def _administrative_ids(ids, _id=None):
    if not ids:
        ids = []
    if _id and not _id in ids:
        ids.append(_id)
    
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
    
    return list(set(all_adl_on_cvd))


def save_csv_datas_adl_in_db(datas_file: dict, type_object="adl") -> str:
    """Function to save the CSV datas in database"""
    
    message = ""
    summary_errors = ""
    account_created = 0
    account_already_exist = 0
    at_least_one_error = False
    at_least_one_save = False

    if datas_file:
        count = 0
        long = len(list(datas_file.values())[0])
        while count < long:
            try:
                canton = datas_file.get("CANTON", {}).get(count)
                village = datas_file.get("VILLAGE", {}).get(count)
                email = datas_file.get("ADRESS_EMAIL", {}).get(count)
                password = datas_file.get("ADRESS_PASSWORD", {}).get(count)
                phone_number = datas_file.get("ADRESS_PHONE_NUMBER", {}).get(count)

                # phone_number not exist (None, nan, ""), we set it to 22800000000 by default
                if phone_number in [None, "", "nan", "NaN"] or str(phone_number) in ["None", "", "nan", "NaN"] or (isinstance(phone_number, float) and math.isnan(phone_number)):
                    phone_number = "22800000000"

                if not canton or not village or not email or not password:
                    summary_errors += f"Line {count+2} : Missing data - CANTON: {canton}, VILLAGE: {village}, ADRESS_EMAIL: {email}\n"
                else:
                    canton = str(canton).upper()
                    village = str(village).upper()

                    village_founded = mis_objects_call.filter_objects(AdministrativeLevel, parent__name=canton, name=village, type="Village").first()
                    if not village_founded:
                        summary_errors += f"Line {count+2} : This village not exist in database - CANTON: {canton}, VILLAGE: {village}\n"
                    else:
                        user = User.objects.filter(email=email).first()
                        if not user:
                            village_founded_id_str = str(village_founded.id)

                            user = User()
                            user.email = email
                            user.first_name = village
                            user.last_name = canton
                            user.phone_number = phone_number

                            user.save()

                            user = User.objects.get(email=email)

                            if hasattr(user, 'governmentworker'):
                                governmentworker = GovernmentWorker.objects.get(id=user.governmentworker.id)
                            else:
                                governmentworker = GovernmentWorker()
                                governmentworker.user = user
                                governmentworker.department = 1

                            governmentworker.administrative_id = village_founded_id_str
                            
                            if village_founded_id_str != "1":
                                governmentworker.administrative_ids = _administrative_ids([], village_founded_id_str)
                                governmentworker.additional_administrative_ids = list()
                            else:
                                governmentworker.administrative_ids = list()
                                governmentworker.additional_administrative_ids = list()

                            governmentworker.save()

                            account_created += 1
                            at_least_one_save = True
                        else:
                            user.phone_number = phone_number
                            user.save()
                            
                            account_already_exist += 1
                            summary_errors += f"Line {count+2} : This email already exist in database - ADRESS_EMAIL: {email}\n"
            except Exception as exc:
                    at_least_one_error = True
                    summary_errors += f"Line {count+2} : An error has occurred - CANTON: {canton}, VILLAGE: {village}, ADRESS_EMAIL: {email}, ADRESS_PHONE_NUMBER: {phone_number} - Error details: {str(exc)}\n"

            print(canton, village, email, password, phone_number)

            count += 1


    message = ""
    if at_least_one_save and not at_least_one_error:
        message = _("Success!")
    elif not at_least_one_save and not at_least_one_error:
        message = _("No items have been saved!")
    elif not at_least_one_save and at_least_one_error:
        message = _("A problem has occurred!")
    elif at_least_one_save and at_least_one_error:
        message = _("Some element(s) have not been saved!")

    
    if not os.path.exists("media/logs/errors"):
        os.makedirs("media/logs/errors")
    file_path = "logs/errors/upload_priorities_logs_errors_" + str(datetime.today().replace(microsecond=0)).replace("-", "").replace(":", "").replace(" ", "_") + ".txt"
    
    if type_object=="subproject":
        file_path = file_path.replace("upload_priorities_logs_errors_", "upload_subprojects_logs_errors_")


    messages = "##########################################################Summary###################################################################\n"
    messages += f'\nNumber of accounts created: {account_created}'
    messages += f'\nNumber of accounts already exist: {account_already_exist}'

    messages += "\n\n##########################################################Details of errors###################################################################\n"
    messages += summary_errors if summary_errors else "No errors found."

    f = open("media/"+file_path, "a")
    f.write(messages)
    f.close()
    


    return (message, file_path.replace("/", "\\\\") if platform == "win32" else file_path)