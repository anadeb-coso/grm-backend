from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import generic
from django.contrib.auth.hashers import check_password

from dashboard.mixins import AJAXRequestMixin, JSONResponseMixin
from privacy.functions import get_last_category_password


class GetLastCategoryPasswordView(AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):
    def get(self, request, *args, **kwargs):
        category_id = request.GET.get('category_id')

        return self.render_to_json_response(
            get_last_category_password(category_id),
            safe=False
        )
    

class ValidatedMyPasswordByLastCategoryPasswordView(AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):
    def get(self, request, *args, **kwargs):
        category_id = request.GET.get('category_id')
        password = request.GET.get('password')
        
        last_category_password = get_last_category_password(category_id)
        
        return self.render_to_json_response(
            check_password(password, last_category_password.password) if (password and last_category_password) else False,
            safe=False
        )
    
    