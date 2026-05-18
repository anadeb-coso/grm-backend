from django.shortcuts import redirect
from django.contrib import messages
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
import pandas as pd
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils.translation import gettext_lazy as _

from dashboard.mixins import PageMixin
from administrativelevels.models import AdministrativeLevel, GeographicalUnit, CVD
from grm.libraries import convert_file_to_dict, download_file
from administrativelevels import functions as administrativelevels_functions
from authentication.permissions import (
    AdminPermissionRequiredMixin
)
from dashboard.adls.functions import save_csv_datas_adl_in_db




class UploadCSVView(PageMixin, LoginRequiredMixin, AdminPermissionRequiredMixin, TemplateView):
    """Class to upload and save the administrativelevels"""

    template_name = 'upload.html'
    context_object_name = 'Upload'
    title = _("Upload")
    active_level1 = 'grm'
    breadcrumb = [
        {
            'url': '',
            'title': title
        },
    ]

    def post(self, request, *args, **kwargs):
        datas = {}
        redirect_path = 'adls:list'
        _type = request.POST.get('_type')

        if _type == "grm":
            """Load Subprojects"""
            redirect_path = "adls:list"
            try:
                datas = convert_file_to_dict.conversion_file_xlsx_to_dict(request.FILES.get('file'), request.POST.get('sheet_name'))
            except pd.errors.ParserError as exc:
                datas = convert_file_to_dict.conversion_file_csv_to_dict(request.FILES.get('file'), request.POST.get('sheet_name'))
            except Exception as exc:
                messages.info(request, _("An error has occurred..."))
            # try:
            message, file_path = save_csv_datas_adl_in_db(datas, _type) # call function to save CSV datas in database
            
            return download_file.download(request, file_path, "text/plain")
            
            # except Exception as exc:
            #     raise Http404
        

        if message:
            messages.info(request, message)

        return redirect(redirect_path)
    
    def get(self, request, *args, **kwargs):
        context = super(UploadCSVView, self).get(request, *args, **kwargs)
        return context
