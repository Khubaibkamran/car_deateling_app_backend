"""Payment provider boundary.

There is no real card processor connected yet, so `charge()` approves every charge and returns a
made-up reference. When Stripe (or another provider) is added, only this module changes: take a
payment-method token instead of a `SavedCard`, call the provider, and raise `PaymentDeclined` on failure.
"""
import uuid
from dataclasses import dataclass
from decimal import Decimal

from rest_framework.exceptions import APIException

from .models import SavedCard


class PaymentDeclined(APIException):
    status_code = 402
    default_detail = 'Your payment was declined. Try another card.'
    default_code = 'payment_declined'


@dataclass
class Charge:
    reference: str
    method_label: str


def charge(amount: Decimal, card: SavedCard) -> Charge:
    if card.exp_year * 12 + card.exp_month < _this_month():
        raise PaymentDeclined('This card has expired.')
    return Charge(reference=f'sim_{uuid.uuid4().hex}', method_label=card.label)


def refund(reference: str) -> None:
    """Return a payment's money. Nothing to do while charges are simulated."""


def _this_month() -> int:
    from django.utils import timezone

    now = timezone.now()
    return now.year * 12 + now.month
