from django.utils import timezone
from django.utils.timesince import timesince
from rest_framework import serializers

from .models import DeviceToken, Notification


class NotificationSerializer(serializers.ModelSerializer):
    booking_id = serializers.IntegerField(read_only=True)
    group = serializers.SerializerMethodField()
    time_ago = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ['id', 'type', 'title', 'body', 'booking_id', 'read', 'created_at', 'group', 'time_ago']
        read_only_fields = fields

    def get_group(self, obj) -> str:
        """"Today" or "Earlier", matching the app's two sections."""
        return 'Today' if obj.created_at.date() == timezone.now().date() else 'Earlier'

    def get_time_ago(self, obj) -> str:
        delta = timezone.now() - obj.created_at
        if delta.total_seconds() < 60:
            return 'Just now'
        return f'{timesince(obj.created_at).split(",")[0]} ago'


class DeviceTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceToken
        fields = ['token', 'platform']
        extra_kwargs = {'token': {'validators': []}}  # a token may already exist; the view moves it
