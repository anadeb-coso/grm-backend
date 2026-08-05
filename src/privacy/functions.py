from privacy.models import IssueCategoryPassword
from grm.utils import cryptography_fernet_decrypt


def get_last_category_password(category_id):
    return IssueCategoryPassword.objects.filter(issue_category_id=category_id).last()

def get_all_category_passwords(category_id):
    return IssueCategoryPassword.objects.filter(issue_category_id=category_id)

def get_all_privacy_passwords(category_id):
    passwords_clear = []
    for cat_pass in  IssueCategoryPassword.objects.filter(issue_category_id=category_id):
        if cat_pass.password_data_encrypt and cat_pass.key:
            passwords_clear.append(cryptography_fernet_decrypt(cat_pass.password_data_encrypt, cat_pass.key))

    passwords_clear.reverse()

    return passwords_clear