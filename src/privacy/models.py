from django.db import models
from django.utils.translation import gettext_lazy as _

from grm.models_base import BaseModel
from authentication.models import User
from grm.constants import ISSUES_CATEGORY
# Create your models here.


class IssueCategpryPassword(BaseModel):
    issue_category_id = models.IntegerField(choices=ISSUES_CATEGORY, verbose_name=_("Category"))
    password = models.CharField(verbose_name=_("Password"), max_length=255)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, verbose_name=_("User"), null=True)
    key = models.CharField(max_length=255, blank=True, null=True)
    password_data_encrypt = models.CharField(max_length=255, blank=True, null=True)
