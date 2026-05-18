from django.db import models
from django.utils.translation import gettext_lazy as _

from grm.models_base import BaseModel

# Create your models here.

class Wave(BaseModel):
    number = models.IntegerField()
    description = models.TextField()
    administrative_ids = models.JSONField(verbose_name=_('administrative levels')) # list of administrative levels ids
    begin = models.DateField()
    end = models.DateField(blank=True, null=True)