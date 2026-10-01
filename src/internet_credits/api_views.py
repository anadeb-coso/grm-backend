"""API REST (JWT) des confirmations de forfait internet, utilisée par le mobile DCC
(cdd-frontend/src/services/grm/internetCredits.tsx). Le mobile MGP passe, lui, par la sync
WatermelonDB (sync/views.py) — les deux s'appuient sur les mêmes règles (services.py)."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import InternetCreditConfirmation
from .serializers import ConfirmationCreateSerializer, notification_payload


class NotificationListView(APIView):
    """Notifications de forfait en attente pour l'utilisateur connecté (membre CVGP ou FC/AC)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        items = [notification_payload(request.user, b) for b in services.pending_notifications(request.user)]
        return Response({'count': len(items), 'results': items})


class ConfirmationCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ConfirmationCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'code': 'invalid', 'detail': 'Données invalides.', 'errors': serializer.errors}, status=400)
        data = dict(serializer.validated_data)
        for key in ('id', 'beneficiary'):
            if data.get(key) is not None:
                data[key] = str(data[key])
        try:
            confirmation, created = services.create_confirmation(
                request.user, data, InternetCreditConfirmation.SOURCE_CDD_MOBILE,
            )
        except services.ConfirmationRejected as exc:
            return Response({'code': exc.code, 'detail': exc.message}, status=exc.status)
        return Response(
            {
                'id': str(confirmation.id),
                'beneficiary': str(confirmation.beneficiary_id),
                'role': confirmation.role,
                'confirmed_at': confirmation.confirmed_at.isoformat(),
            },
            status=201 if created else 200,
        )
