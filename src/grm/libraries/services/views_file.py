import json
from django.http import HttpResponse
from grm.libraries import convert_file_to_dict
# from django.views.decorators.csrf import csrf_exempt

# @csrf_exempt
def get_excel_sheets_names(request):
    names = []
    if request.method == "POST":
        names = convert_file_to_dict.get_excel_sheets_names(request.FILES.get('file'))
    return HttpResponse(json.dumps(
        {"names": names}
        ), content_type="application/json")


