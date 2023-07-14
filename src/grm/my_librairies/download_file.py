import os
from django.conf import settings
from django.http import HttpResponse, Http404

def download(request, path, content_type="application/pdf", param_download=True):
    file_path = os.path.join(settings.MEDIA_ROOT, path)
    if os.path.exists(file_path):
        with open(file_path, 'rb') as fh:
            response = HttpResponse(fh.read(), content_type)
            # response['Content-Disposition'] = 'inline; filename=' + os.path.basename(file_path)
            content = 'inline; filename=' + os.path.basename(file_path)
            if param_download:
                content = "attachment; filename=" + os.path.basename(file_path)
            response['Content-Disposition'] = content
            return response
    raise Http404

def download_file(data, file_name_with_extension, content_type="application/pdf", param_download=True):
    response = HttpResponse(data, content_type)
    content = 'inline; filename=' + file_name_with_extension
    if param_download:
        content = "attachment; filename=" + file_name_with_extension
    response['Content-Disposition'] = content
    return response