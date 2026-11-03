"""MGP account of a person, read by the SIG (COSOMIS) for its Profile page: the SIG does not read the MGP
database. Server-to-server call authenticated by the shared secret (HasGrmServiceKey)."""
from django.contrib.auth import get_user_model
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import HasGrmServiceKey

User = get_user_model()


class UserAccountView(APIView):
    """GET ?email=... → {exists, username, first_name, last_name, phone_number, is_superuser, groups,
    date_joined, last_login}. `exists: false` when no active account has this e-mail."""
    permission_classes = [HasGrmServiceKey]

    def get(self, request):
        email = (request.query_params.get('email') or '').strip()
        if not email:
            return Response({'detail': 'email is required'}, status=400)
        user = User.objects.filter(email__iexact=email, is_active=True).order_by('pk').first()
        if user is None:
            return Response({'exists': False})
        return Response({
            'exists': True,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'phone_number': getattr(user, 'phone_number', None),
            'is_superuser': user.is_superuser,
            'groups': sorted(user.groups.values_list('name', flat=True)),
            'date_joined': user.date_joined.isoformat() if user.date_joined else None,
            'last_login': user.last_login.isoformat() if user.last_login else None,
        })
