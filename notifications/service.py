"""Create in-app notifications. Call `notify()` from anywhere something worth telling a user happens."""
from .models import Notification


def notify(user, type: str, title: str, body: str, booking=None) -> Notification:
    # Push delivery (Expo) will hook in here once the app registers device tokens in production.
    return Notification.objects.create(user=user, type=type, title=title[:120], body=body[:300], booking=booking)
