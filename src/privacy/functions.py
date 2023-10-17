from privacy.models import IssueCategpryPassword
from grm.utils import (
    get_administrative_level_descendants, get_auto_increment_id, get_child_administrative_regions,
    get_parent_administrative_level, get_administrative_level_descendants_using_mis, 
    get_child_administrative_regions_using_mis, cryptography_fernet_encrypt,
    cryptography_fernet_decrypt, delete_file_on_download_file
)


def get_last_category_password(category_id):
    return IssueCategpryPassword.objects.filter(issue_category_id=category_id).last()

def get_all_category_passwords(category_id):
    return IssueCategpryPassword.objects.filter(issue_category_id=category_id)

def get_all_privacy_passwords(category_id):
    passwords_clear = []
    for cat_pass in  IssueCategpryPassword.objects.filter(issue_category_id=category_id):
        if cat_pass.password_data_encrypt and cat_pass.key:
            passwords_clear.append(cryptography_fernet_decrypt(cat_pass.password_data_encrypt, cat_pass.key))

    passwords_clear.reverse()

    return passwords_clear