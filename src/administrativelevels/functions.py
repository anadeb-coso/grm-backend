from administrativelevels import models as administrativelevels_models
from grm.call_objects_from_other_db import mis_objects_call
from administrativelevels.models import AdministrativeLevel

def get_cascade_administrative_levels_by_administrative_level_id(_id):
    print(_id)
    if _id and _id not in (1, "1"): #1 == Country
        ad_obj = administrativelevels_models.AdministrativeLevel.objects.using('mis').get(id=int(_id))

        ads = ad_obj.administrativelevel_set.get_queryset()
        _type = ad_obj.type

        if _type == "Region":
            regions = [ad_obj]
            prefectures = ads
            communes = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(parent_id__in=[o.id for o in prefectures])
            cantons = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(parent_id__in=[o.id for o in communes])
            villages = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(parent_id__in=[o.id for o in cantons])
        elif _type == "Prefecture":
            regions = []
            prefectures = [ad_obj]
            communes = ads
            cantons = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(parent_id__in=[o.id for o in communes])
            villages = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(parent_id__in=[o.id for o in cantons])
        elif _type == "Commune":
            regions = []
            prefectures = []
            communes = [ad_obj]
            cantons = ads
            villages = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(parent_id__in=[o.id for o in cantons])
        elif _type == "Canton":
            regions = []
            prefectures = []
            communes = []
            cantons = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(id=ad_obj.id)
            villages = ads
        elif _type == "Village":
            regions = []
            prefectures = []
            communes = []
            cantons = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(id=0)
            villages = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(id=ad_obj.id)
        else:
            regions = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(type="Region")
            prefectures = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(type="Prefecture")
            communes = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(type="Commune")
            cantons = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(type="Canton")
            villages = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(type="Village")
    else:
        regions = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(type="Region")
        prefectures = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(type="Prefecture")
        communes = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(type="Commune")
        cantons = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(type="Canton")
        villages = administrativelevels_models.AdministrativeLevel.objects.using('mis').filter(type="Village")

    # return list(regions) + list(prefectures) + list(communes) + list(cantons) + list(villages)
    return list(cantons.order_by("name")) , list(villages.order_by("name"))



def get_object_by_type_and_object(_type, obj):
    if obj:
        if obj.type == _type:
            return obj
        return get_object_by_type_and_object(_type, obj.parent)
    return None

def get_ald_parent_by_type_and_child_id(_type, child_id):
    child_obj =  mis_objects_call.filter_objects(AdministrativeLevel, id=child_id).first()
    return get_object_by_type_and_object(_type, child_obj)