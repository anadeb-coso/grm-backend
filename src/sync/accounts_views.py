from django.contrib.auth import get_user_model
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class NotificationAccountsView(APIView):
    """Comptes actifs que l'auteur d'un commentaire peut ajouter aux destinataires de ses
    notifications (grm-frontend : zone de commentaire). Identifiant et nom uniquement : le mobile
    met cette liste en cache pour pouvoir commenter hors-ligne."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        users = get_user_model().objects.filter(is_active=True).order_by('first_name', 'last_name', 'id')
        accounts = [
            {'id': user.id, 'name': (user.name.strip() or user.email or user.username)}
            for user in users
        ]
        return Response(accounts)
