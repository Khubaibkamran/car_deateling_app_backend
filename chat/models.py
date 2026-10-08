from django.conf import settings
from django.db import models


class Conversation(models.Model):
    """A chat between a customer and a technician (for a booking) or the support team."""

    class Kind(models.TextChoices):
        BOOKING = 'booking', 'Booking'
        SUPPORT = 'support', 'Support'

    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.BOOKING)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='conversations')
    # The technician, or a staff member for support chats.
    counterpart = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='conversations_as_counterpart'
    )
    booking = models.ForeignKey('bookings.Booking', null=True, blank=True, on_delete=models.SET_NULL, related_name='conversations')
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ['-last_message_at', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['customer', 'counterpart', 'booking'], name='one_chat_per_booking'),
        ]

    def other_party(self, user):
        return self.counterpart if user.pk == self.customer_id else self.customer

    def includes(self, user) -> bool:
        return user.pk in (self.customer_id, self.counterpart_id)


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    text = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at', 'id']
