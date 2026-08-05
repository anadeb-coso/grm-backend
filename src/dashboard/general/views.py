from django.apps import apps
from django.contrib import messages
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView

from dashboard.mixins import AJAXRequestMixin, JSONResponseMixin, ModalFormMixin
from .forms import DeleteConfirmForm
from authentication.permissions import AdminPermissionRequiredMixin
from grm.models_base import TimestampedSyncModel
from issue.models import Issue

#Delete
class DeleteObjectFormView(AJAXRequestMixin, ModalFormMixin, AdminPermissionRequiredMixin, JSONResponseMixin,
                                      FormView):
    form_class = DeleteConfirmForm
    id_form = "object_deletion_form"
    title = _('Confirm deletion')
    submit_button = _('Confirm')
    form_class_color = 'danger'

    def post(self, request, *args, **kwargs):
        form = None
        if self.kwargs.get('object_id') and self.kwargs.get('type'):
            ClassModal = None
            obj = None
            if self.kwargs.get('type') == "Issue":
                obj = Issue.objects.filter(auto_increment_id=self.kwargs['object_id']).first()
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
        # Suppression logique pour les issues (comme l'ancien code CouchDB, `confirmed=False`
        # plutôt qu'une suppression physique) ; tombstone logique (`is_deleted=True`) pour tout
        # autre modèle synchronisé avec le mobile (`TimestampedSyncModel` — Comment, Reason, Adl,
        # Phase, Task, BpProject...) ; suppression réelle seulement pour les modèles qui ne sont
        # jamais synchronisés. Un `.delete()` sur un modèle synchronisé fait disparaître la ligne
        # avant que le pull incrémental n'ait pu calculer un tombstone à partir d'elle : la
        # suppression restait alors invisible côté mobile indéfiniment, quel que soit le nombre de
        # rafraîchissements.
        if isinstance(obj, Issue):
            obj.confirmed = False
            # `updated_at` doit être explicitement listé pour que Django l'auto-rafraîchisse
            # (`QuerySet.update()`/`save(update_fields=...)` sans lui n'appliquent pas `auto_now`)
            # — sinon cette "suppression" logique reste invisible au pull incrémental mobile.
            obj.save(update_fields=['confirmed', 'updated_at'])
        elif isinstance(obj, TimestampedSyncModel):
            obj.is_deleted = True
            obj.save(update_fields=['is_deleted', 'updated_at'])
        else:
            obj.delete()

        msg = _("The Step was successfully removed.")
        messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')

        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)
#And Delete
