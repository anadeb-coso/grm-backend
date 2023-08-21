from django.apps import apps
from django.contrib import messages
from django.shortcuts import render
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView

from dashboard.mixins import AJAXRequestMixin, JSONResponseMixin, ModalFormMixin
from .forms import DeleteConfirmForm
from authentication.permissions import AdminPermissionRequiredMixin
from client import get_db

COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE

#Delete
class DeleteObjectFormView(AJAXRequestMixin, ModalFormMixin, AdminPermissionRequiredMixin, JSONResponseMixin,
                                      FormView):
    form_class = DeleteConfirmForm
    id_form = "object_deletion_form"
    title = _('Confirm deletion')
    submit_button = _('Confirm')
    form_class_color = 'danger'
    grm_db = get_db(COUCHDB_GRM_DATABASE)

    def post(self, request, *args, **kwargs):
        form = None
        if self.kwargs.get('object_id') and self.kwargs.get('type'):
            ClassModal = None
            obj = None
            if self.kwargs.get('type') == "Issue":
                try:
                    obj = self.grm_db.get_query_result({
                        "auto_increment_id": self.kwargs['object_id'],
                        "type": 'issue'
                    })
                    obj = self.grm_db[
                        self.grm_db.get_query_result({
                            "auto_increment_id": self.kwargs['object_id'],
                            "type": 'issue'
                        })[0][0]['_id']
                    ]
                except:
                    pass
            else:
                for app_conf in apps.get_app_configs():
                    try:
                        ClassModal = app_conf.get_model(self.kwargs.get('type').lower())
                        break # stop as soon as it is found
                    except LookupError:
                        # no such model in this application
                        pass
            
            form = DeleteConfirmForm(request.POST)
            if obj:
                if form and form.is_valid():
                    return self._delete_object(obj)
            elif ClassModal:
                obj = ClassModal.objects.get(id=self.kwargs.get('object_id'))
                if form and form.is_valid():
                    return self._delete_object(obj)
        
        msg = _("An error has occurred...")
        messages.add_message(self.request, messages.ERROR, msg, extra_tags='error')

        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)
    
    def _delete_object(self, obj):
        
        obj.delete()
        
        msg = _("The Step was successfully removed.")
        messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')

        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)
#And Delete