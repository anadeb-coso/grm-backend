from rest_framework import permissions
#from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework.response import Response
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from django.db.models import Q

from administrativelevels.serializers import AdministrativeLevelSerializer
from administrativelevels.models import AdministrativeLevel
from administrativelevels.functions import get_cascade_administrative_levels_by_administrative_level_id
from client import get_db


class RestAdministrativeLevelFilter(APIView):
    #authentication_classes = [SessionAuthentication, BasicAuthentication]
    # permission_classes = (permissions.IsAuthenticated,)
    def get(self, request, *args, **kwargs):
        _filters = dict(request.GET)
        filters = {k:(float(v[0]) if v[0].isdigit() else (None if v[0] == 'null' else v[0])) for k, v in _filters.items()}
        administrativelevel = filters.get("administrativelevel")
        ads = AdministrativeLevel.objects.using('mis').filter(type=administrativelevel)
        if administrativelevel:
            del filters['administrativelevel']
        _filters = {}
        ads = ads.filter(**filters)

        ads_ser = []
        for ad in ads:
            ad_ser = AdministrativeLevelSerializer(ad).data
            if administrativelevel in ("Region", "Prefecture", "Commune", "Canton", "Village"):
                ad_ser["country"] = "1"
            if administrativelevel == "Prefecture":
                ad_ser["region"] = ad.parent_id
            elif administrativelevel == "Commune":
                ad_ser["prefecture"] = ad.parent_id
                ad_ser["region"] = ad.parent.parent_id
            elif administrativelevel == "Canton":
                ad_ser["commune"] = ad.parent_id
                ad_ser["prefecture"] = ad.parent.parent_id
                ad_ser["region"] = ad.parent.parent.parent_id
            elif administrativelevel == "Village":
                ad_ser["canton"] = ad.parent_id
                ad_ser["commune"] = ad.parent.parent_id
                ad_ser["prefecture"] = ad.parent.parent.parent_id
                ad_ser["region"] = ad.parent.parent.parent.parent_id
            ads_ser.append(ad_ser)

        return Response(
            ads_ser, status.HTTP_200_OK
        )
        
class RestAdministrativeLevelFilterByADL(APIView):
    #authentication_classes = [SessionAuthentication, BasicAuthentication]
    # permission_classes = (permissions.IsAuthenticated,)
    def get(self, request, *args, **kwargs):
        _filters = dict(request.GET)
        filters = {k:(float(v[0]) if v[0].isdigit() else (None if v[0] == 'null' else v[0])) for k, v in _filters.items()}
        administrative_region = int(filters.get("administrative_region"))

        # eadl_db = get_db()
        # doc_user = {}
        
        # try:
        #     doc_user = eadl_db[eadl_db.get_query_result({"type": "adl", "representative.id": user_id})[0][0]["_id"]]
        # except Exception as exc:
        #     return Response({
        #             'message' : 'error : ' + exc.__str__()
        #         }, status.HTTP_400_BAD_REQUEST)
        print(administrative_region)
        cantons, villages = get_cascade_administrative_levels_by_administrative_level_id(administrative_region)
        
        cantons_ser = []
        villages_ser = []
        for canton in cantons:
            ad_ser = AdministrativeLevelSerializer(canton).data
            ad_ser["country"] = "1"
            ad_ser["commune"] = canton.parent_id
            ad_ser["prefecture"] = canton.parent.parent_id
            ad_ser["region"] = canton.parent.parent.parent_id
            cantons_ser.append(ad_ser)
        for village in villages:
            ad_ser = AdministrativeLevelSerializer(village).data
            ad_ser["country"] = "1"
            ad_ser["canton"] = village.parent_id
            ad_ser["commune"] = village.parent.parent_id
            ad_ser["prefecture"] = village.parent.parent.parent_id
            ad_ser["region"] = village.parent.parent.parent.parent_id
            villages_ser.append(ad_ser)
        return Response(
            {"cantons": cantons_ser, "villages": villages_ser}, status.HTTP_200_OK
        )
        