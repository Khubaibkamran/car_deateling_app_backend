from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Type(models.TextChoices):
        BOOKING = 'booking', 'Booking'
        ON_THE_WAY = 'onTheWay', 'On the way'
        COMPLETED = 'completed', 'Completed'
        PAYMENT = 'payment', 'Payment'
        PROMO = 'promo', 'Promotion'
        JOB = 'job', 'Job'
        REMINDER = 'reminder', 'Reminder'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    type = models.CharField(max_length=20, choices=Type.choices)
    title = models.CharField(max_length=120)
    body = models.CharField(max_length=300)
    booking = models.ForeignKey('bookings.Booking', null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['user', 'read'])]

    def __str__(self) -> str:
        return f'{self.user_id}: {self.title}'


class DeviceToken(models.Model):
    """An Expo push token for one phone, so the server can send push notifications."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='device_tokens')
    token = models.CharField(max_length=200, unique=True)
    platform = models.CharField(max_length=10, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
