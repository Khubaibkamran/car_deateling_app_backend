from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DeviceToken, Notification
from .serializers import DeviceTokenSerializer, NotificationSerializer


@extend_schema(tags=['Notifications'])
class NotificationListView(generics.ListAPIView):
    """Your notifications, newest first. Add `?unread=true` to see only unread ones."""

    serializer_class = NotificationSerializer

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user)
        if self.request.query_params.get('unread', '').lower() in {'1', 'true', 'yes'}:
            qs = qs.filter(read=False)
        return qs


@extend_schema(tags=['Notifications'], responses={200: OpenApiResponse(description='`{"unread": 3}`')})
class UnreadCountView(APIView):
    """How many notifications are unread (the number on the bell)."""

    def get(self, request):
        return Response({'unread': Notification.objects.filter(user=request.user, read=False).count()})


@extend_schema(tags=['Notifications'], request=None, responses={200: NotificationSerializer})
class MarkReadView(APIView):
    def post(self, request, pk):
        notification = generics.get_object_or_404(Notification, pk=pk, user=request.user)
        if not notification.read:
            notification.read = True
            notification.save(update_fields=['read'])
        return Response(NotificationSerializer(notification, context={'request': request}).data)


@extend_schema(tags=['Notifications'], request=None, responses={200: OpenApiResponse(description='`{"updated": 3}`')})
class MarkAllReadView(APIView):
    def post(self, request):
        updated = Notification.objects.filter(user=request.user, read=False).update(read=True)
        return Response({'updated': updated})


@extend_schema(tags=['Notifications'], request=DeviceTokenSerializer, responses={204: None})
class RegisterDeviceView(APIView):
    """Save this phone's Expo push token so the server can send it push notifications."""

    def post(self, request):
        serializer = DeviceTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # A token belongs to one account at a time (e.g. after someone else signs in on the same phone).
        DeviceToken.objects.update_or_create(
            token=serializer.validated_data['token'],
            defaults={'user': request.user, 'platform': serializer.validated_data.get('platform', '')},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
