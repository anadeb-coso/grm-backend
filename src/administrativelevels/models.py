from email.policy import default
from django.db import models
from django.db.models.signals import post_save
from django.db import models
from typing import TypeVar, Any

from grm.models_base import BaseModel

_QS = TypeVar("_QS", bound="models._BaseQuerySet[Any]")
class CustomQuerySet(models.QuerySet):
    def get_administrative_level_descendants_using_mis(self, adl_db, parent_id, ids, user=None):
        data = []
        if parent_id:
            if int(parent_id) == 1:
                data = AdministrativeLevel.objects.using('mis').filter(type="Region")
            else:
                data = AdministrativeLevel.objects.using('mis').filter(parent_id=int(parent_id))
            
        descendants_ids = [obj.id for obj in data]
        for descendant_id in descendants_ids:
            self.get_administrative_level_descendants_using_mis(adl_db, descendant_id, ids, user)
            ids.append(str(descendant_id))
        return ids
    
    def get_administrative_level_ascendants_using_mis(self, adl_db, child_id, ids, user=None):
        data = []
        if child_id and str(child_id).isdigit():
            child_ad_obj = list(AdministrativeLevel.objects.using('mis').filter(id=int(child_id)))
            if child_ad_obj:
                if child_ad_obj[0].type == "Region":
                    data = []
                else:
                    data.append(child_ad_obj[0].parent)
            
        ascendants_ids = [obj.id for obj in data]
        for ascendant_id in ascendants_ids:
            self.get_administrative_level_ascendants_using_mis(adl_db, ascendant_id, ids, user)
            ids.append(str(ascendant_id))
        return ids
    
    def filter_by_government_worker(self, user, ascendant=True, descendant=True) -> _QS:
        if user and hasattr(user, 'governmentworker') and user.governmentworker.administrative_id not in (None, '', '1', 1) and descendant and descendant:
            ids = list(self.get_administrative_level_ascendants_using_mis(None, user.governmentworker.administrative_id, [], user)) if ascendant else []
            
            ids += list(self.get_administrative_level_descendants_using_mis(None, user.governmentworker.administrative_id, [], user)) if descendant else []
            ids += [str(user.governmentworker.administrative_id)]
            ids = list(set(ids))
            l = []
            for o in self:
                if str(o.id) in ids:
                    l.append(o)
                    
            return l
            
            

        return self


# Create your models here.

    
class AdministrativeLevel(BaseModel):
    name = models.CharField(max_length=255)
    parent = models.ForeignKey('AdministrativeLevel', null=True, blank=True, on_delete=models.CASCADE)
    geographical_unit = models.ForeignKey('GeographicalUnit', null=True, blank=True, on_delete=models.CASCADE)
    cvd = models.ForeignKey('CVD', null=True, blank=True, on_delete=models.CASCADE)
    type = models.CharField(max_length=255)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    frontalier = models.BooleanField(default=True)
    rural = models.BooleanField(default=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    no_sql_db_id = models.CharField(null=True, blank=True, max_length=255)

    objects = CustomQuerySet.as_manager()

    class Meta:
        unique_together = ['name', 'parent', 'type']

    def __str__(self):
        return self.name

    def get_list_priorities(self):
        """Method to get the list of the all priorities that the administrative is linked"""
        return self.villagepriority_set.get_queryset()
    
    # def get_list_subprojects(self):
    #     """Method to get the list of the all subprojects that the administrative is linked"""
    #     return self.subproject_set.get_queryset()
    def get_list_subprojects(self):
        """Method to get the list of the all subprojects that the administrative is linked"""
        if self.cvd:
            return self.cvd.subproject_set.get_queryset()
        return []


class GeographicalUnit(BaseModel):
    canton = models.ForeignKey('AdministrativeLevel', null=True, blank=True, on_delete=models.CASCADE)
    attributed_number_in_canton = models.IntegerField()
    unique_code = models.CharField(max_length=100, unique=True)
    description = models.TextField(null=True, blank=True)

    class Meta:
        unique_together = ['canton', 'attributed_number_in_canton']

    def get_name(self):
        administrativelevels = self.get_villages()
        name = ""
        count = 1
        length = len(administrativelevels)
        for adl in administrativelevels:
            name += adl.name
            if length != count:
                name += "/"
            count += 1
        return name if name else self.unique_code
    
    def get_villages(self):
        return self.administrativelevel_set.get_queryset()

    def get_cvds(self):
        return self.cvd_set.get_queryset()
    
    def __str__(self):
        return self.get_name()
    

class CVD(BaseModel):
    name = models.CharField(max_length=255)
    geographical_unit = models.ForeignKey('GeographicalUnit', on_delete=models.CASCADE)
    headquarters_village = models.ForeignKey('AdministrativeLevel', null=True, blank=True, on_delete=models.CASCADE, related_name='headquarters_village_of_the_cvd')
    attributed_number_in_canton = models.IntegerField(null=True, blank=True)
    unique_code = models.CharField(max_length=100, unique=True)
    president_name_of_the_cvd = models.CharField(max_length=100, null=True, blank=True)
    president_phone_of_the_cvd = models.CharField(max_length=15, null=True, blank=True)
    treasurer_name_of_the_cvd = models.CharField(max_length=100, null=True, blank=True)
    treasurer_phone_of_the_cvd = models.CharField(max_length=15, null=True, blank=True)
    secretary_name_of_the_cvd = models.CharField(max_length=100, null=True, blank=True)
    secretary_phone_of_the_cvd = models.CharField(max_length=15, null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    def get_name(self):
        administrativelevels = self.get_villages()
        if self.name:
            return self.name
        
        name = ""
        count = 1
        length = len(administrativelevels)
        for adl in administrativelevels:
            name += adl.name
            if length != count:
                name += "/"
            count += 1
        return name if name else self.unique_code
    
    def get_villages(self):
        return self.administrativelevel_set.get_queryset()
    
    def get_canton(self):
        if self.headquarters_village:
            return self.headquarters_village.parent
            
        for obj in self.get_villages():
            return obj.parent
        return None
    
    def get_list_subprojects(self):
        """Method to get the list of the all subprojects"""
        return self.subproject_set.get_queryset()
    
    def __str__(self):
        return self.get_name()
    
