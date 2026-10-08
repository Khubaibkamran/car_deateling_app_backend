"""Business rules for bookings. Views stay thin and call these functions, which each run in one transaction.

Lifecycle:  pending_payment -> confirmed -> assigned -> on_the_way -> in_progress -> completed
            (cancelled is possible until the technician is on the way)
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from chat.models import Conversation
from notifications.models import Notification
from notifications.service import notify
from users.models import TechnicianProfile, User

from . import payments
from .geo import distance_meters, eta_minutes
from .models import (
    Booking,
    BookingPhoto,
    Earning,
    JobChecklistItem,
    Payment,
    Review,
    SavedCard,
    TechnicianLocation,
    Withdrawal,
    money,
)

S = Booking.Status
MAX_DAYS_AHEAD = 90
MIN_LEAD_MINUTES = 30
EARNING_HOLD_HOURS = 24


class StateError(APIException):
    """The booking isn't in a state where this action makes sense."""

    status_code = 409
    default_detail = 'This action isn\'t available right now.'
    default_code = 'invalid_state'


def _require_status(booking: Booking, *allowed: str, message: str | None = None) -> None:
    if booking.status not in allowed:
        raise StateError(message or f'This booking is {booking.get_status_display().lower()}.')


def _hours_until(booking: Booking) -> float:
    return (booking.scheduled_at - timezone.now()).total_seconds() / 3600


# ------------------------------------------------------------------ customer side

@transaction.atomic
def create_booking(
    customer: User, *, vehicle, plan, scheduled_at, address, latitude, longitude, notes='', technician=None
) -> Booking:
    if vehicle.owner_id != customer.pk:
        raise ValidationError({'vehicle': 'This vehicle is not yours.'})
    if not plan.is_active or not plan.service.is_active:
        raise ValidationError({'plan': 'This plan isn\'t available any more.'})
    now = timezone.now()
    if scheduled_at < now + timedelta(minutes=MIN_LEAD_MINUTES):
        raise ValidationError({'scheduled_at': 'Choose a time at least 30 minutes from now.'})
    if scheduled_at > now + timedelta(days=MAX_DAYS_AHEAD):
        raise ValidationError({'scheduled_at': f'You can book up to {MAX_DAYS_AHEAD} days ahead.'})

    if technician is not None:
        profile = getattr(technician, 'technician_profile', None)
        if technician.role != User.Role.TECHNICIAN or not technician.is_active or profile is None:
            raise ValidationError({'technician': 'Choose a technician from the list.'})
        if not profile.is_available:
            raise ValidationError({'technician': f'{technician.full_name} is not taking jobs right now.'})

    service = plan.service
    booking = Booking.objects.create(
        customer=customer,
        requested_technician=technician,
        vehicle=vehicle,
        service=service,
        plan=plan,
        service_name=service.name,
        plan_tag=plan.tag,
        vehicle_name=vehicle.name,
        vehicle_year=vehicle.year,
        vehicle_color=vehicle.color,
        vehicle_plate=vehicle.plate,
        price=plan.price,
        duration_minutes=plan.expected_minutes,
        scheduled_at=scheduled_at,
        address=address,
        latitude=latitude,
        longitude=longitude,
        notes=notes,
    )
    if technician is not None and not _is_free(technician, booking):
        raise ValidationError({'technician': f'{technician.full_name} is busy at that time. Pick another time or technician.'})
    for i, step in enumerate(service.checklist.all()):
        JobChecklistItem.objects.create(booking=booking, text=step.text, sort_order=i)
    return booking


@transaction.atomic
def pay_booking(booking: Booking, card: SavedCard) -> Booking:
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    _require_status(booking, S.PENDING_PAYMENT, message='This booking has already been paid for or was cancelled.')
    if card.user_id != booking.customer_id:
        raise ValidationError({'card': 'This card is not yours.'})
    if booking.scheduled_at < timezone.now():
        raise ValidationError({'scheduled_at': 'The booked time has already passed. Please book again.'})

    result = payments.charge(booking.price, card)
    Payment.objects.create(
        booking=booking, amount=booking.price, method_label=result.method_label, reference=result.reference
    )
    booking.status = S.CONFIRMED
    booking.paid_at = timezone.now()
    booking.save(update_fields=['status', 'paid_at'])

    notify(booking.customer, Notification.Type.BOOKING, 'Booking confirmed',
           f'Your {booking.service_name} is booked for {_when(booking)}.', booking)
    notify(booking.customer, Notification.Type.PAYMENT, 'Payment received',
           f'We received your payment of ${booking.price} on {result.method_label}.', booking)
    if booking.requested_technician_id:
        # The customer picked someone: that technician decides whether to accept. They can chat meanwhile.
        Conversation.objects.get_or_create(
            customer=booking.customer, counterpart=booking.requested_technician, booking=booking,
            defaults={'kind': Conversation.Kind.BOOKING},
        )
        notify(booking.requested_technician, Notification.Type.JOB, 'New job request',
               f'{booking.customer.full_name} asked for you: {booking.service_name} on {_when(booking)}.', booking)
    else:
        assign_technician(booking)
    booking.refresh_from_db()
    return booking


@transaction.atomic
def cancel_booking(booking: Booking, user: User, reason: str = '') -> Booking:
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    _require_status(booking, S.PENDING_PAYMENT, S.CONFIRMED, S.ASSIGNED,
                    message='This booking can no longer be cancelled.')
    window = settings.CHANGE_WINDOW_HOURS
    if booking.status != S.PENDING_PAYMENT and _hours_until(booking) < window:
        raise StateError(f'Bookings can only be cancelled up to {window} hours before the start time.')

    technician = booking.technician
    was_paid = booking.status != S.PENDING_PAYMENT
    booking.status = S.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.cancel_reason = reason[:200]
    booking.save(update_fields=['status', 'cancelled_at', 'cancel_reason'])

    if was_paid:
        for payment in booking.payments.filter(status=Payment.Status.PAID):
            payments.refund(payment.reference)
            payment.status = Payment.Status.REFUNDED
            payment.save(update_fields=['status'])
        notify(booking.customer, Notification.Type.PAYMENT, 'Booking cancelled',
               f'Your {booking.service_name} was cancelled and ${booking.price} is on its way back to you.', booking)
    if technician:
        notify(technician, Notification.Type.JOB, 'Job cancelled',
               f'{booking.service_name} for {booking.customer.full_name} on {_when(booking)} was cancelled.', booking)
    return booking


@transaction.atomic
def reschedule_booking(booking: Booking, scheduled_at) -> Booking:
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    _require_status(booking, S.CONFIRMED, S.ASSIGNED, message='This booking can no longer be rescheduled.')
    window = settings.CHANGE_WINDOW_HOURS
    if _hours_until(booking) < window:
        raise StateError(f'Bookings can only be rescheduled up to {window} hours before the start time.')
    now = timezone.now()
    if scheduled_at < now + timedelta(hours=window) or scheduled_at > now + timedelta(days=MAX_DAYS_AHEAD):
        raise ValidationError({'scheduled_at': 'Choose a later time within the next 90 days.'})

    previous = booking.technician
    booking.scheduled_at = scheduled_at
    # Keep the same technician only if they are free at the new time.
    if previous and not _is_free(previous, booking, ignore=booking):
        booking.technician = None
        booking.assigned_at = None
        booking.status = S.CONFIRMED
        notify(previous, Notification.Type.JOB, 'Job rescheduled',
               f'{booking.service_name} moved to {_when(booking)} and was removed from your jobs.', booking)
    booking.save(update_fields=['scheduled_at', 'technician', 'assigned_at', 'status'])

    notify(booking.customer, Notification.Type.BOOKING, 'Booking rescheduled',
           f'Your {booking.service_name} is now on {_when(booking)}.', booking)
    if booking.technician:
        notify(booking.technician, Notification.Type.JOB, 'Job rescheduled',
               f'{booking.service_name} moved to {_when(booking)}.', booking)
    else:
        assign_technician(booking)
    booking.refresh_from_db()
    return booking


@transaction.atomic
def submit_review(booking: Booking, customer: User, rating: int, comment: str = '') -> Review:
    _require_status(booking, S.COMPLETED, message='You can only review a completed service.')
    if hasattr(booking, 'review'):
        raise StateError('You already reviewed this service.')
    review = Review.objects.create(
        booking=booking, customer=customer, technician=booking.technician, rating=rating, comment=comment.strip()
    )
    service = booking.service
    service.rating = money((service.rating * service.rating_count + rating) / (service.rating_count + 1))
    service.rating_count += 1
    service.save(update_fields=['rating', 'rating_count'])

    tech = booking.technician
    if tech and hasattr(tech, 'technician_profile'):
        profile = tech.technician_profile
        profile.rating = money((profile.rating * profile.rating_count + rating) / (profile.rating_count + 1))
        profile.rating_count += 1
        profile.save(update_fields=['rating', 'rating_count'])
        notify(tech, Notification.Type.COMPLETED, f'New {rating}-star review',
               f'{customer.full_name} rated your work {rating} star{"s" if rating != 1 else ""}.', booking)
    return review


def tracking(booking: Booking) -> dict:
    """Where the technician is and how long they'll take, for the customer's live map."""
    location = TechnicianLocation.objects.filter(technician=booking.technician).first() if booking.technician_id else None
    data = {'status': booking.status, 'technician_location': None, 'eta_minutes': None}
    if location and booking.status in (S.ON_THE_WAY, S.IN_PROGRESS, S.ASSIGNED):
        meters = distance_meters(location.latitude, location.longitude, booking.latitude, booking.longitude)
        data['technician_location'] = {
            'latitude': location.latitude,
            'longitude': location.longitude,
            'heading': location.heading,
            'updated_at': location.updated_at,
            'distance_meters': round(meters),
        }
        if booking.status == S.ON_THE_WAY:
            data['eta_minutes'] = eta_minutes(meters)
    return data


# ------------------------------------------------------------------ dispatch

def is_free(technician: User, booking: Booking) -> bool:
    """Public name for the free-at-this-time check (also works on a booking that isn't saved)."""
    return _is_free(technician, booking)


def _is_free(technician: User, booking: Booking, ignore: Booking | None = None) -> bool:
    """True if the technician has no other job overlapping this booking (plus a travel buffer)."""
    buffer = timedelta(minutes=settings.JOB_BUFFER_MINUTES)
    start, end = booking.scheduled_at - buffer, booking.ends_at + buffer
    others = Booking.objects.filter(
        technician=technician, status__in=[S.ASSIGNED, S.ON_THE_WAY, S.IN_PROGRESS]
    ).exclude(pk=booking.pk)
    if ignore is not None:
        others = others.exclude(pk=ignore.pk)
    # Bound the query to a sensible window, then do the exact overlap check with each job's own length.
    window = others.filter(scheduled_at__gte=start - timedelta(hours=12), scheduled_at__lte=end)
    return not any(o.scheduled_at < end and o.ends_at > start for o in window)


@transaction.atomic
def assign_technician(booking: Booking) -> User | None:
    """Give the booking to the best free, available technician (highest rating, then fewest jobs)."""
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    if booking.status != S.CONFIRMED or booking.technician_id or booking.requested_technician_id:
        return None

    candidates = (
        User.objects.filter(role=User.Role.TECHNICIAN, is_active=True, technician_profile__is_available=True)
        .select_related('technician_profile')
        .annotate(open_jobs=Count('jobs', filter=Q(jobs__status__in=[S.ASSIGNED, S.ON_THE_WAY, S.IN_PROGRESS])))
        .order_by('-technician_profile__rating', 'open_jobs', 'id')
    )
    for tech in candidates:
        if _is_free(tech, booking):
            _assign(booking, tech)
            return tech
    return None  # stays "confirmed" in the open-jobs pool until someone claims it


@transaction.atomic
def claim_booking(technician: User, booking: Booking) -> Booking:
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    if booking.status != S.CONFIRMED or booking.technician_id:
        raise StateError('This job has already been taken.')
    if booking.requested_technician_id and booking.requested_technician_id != technician.pk:
        raise StateError('This job was requested for another technician.')
    if not technician.technician_profile.is_available:
        raise StateError('Switch on "Available for Jobs" to accept jobs.')
    if not _is_free(technician, booking):
        raise StateError('You already have a job around that time.')
    _assign(booking, technician)
    return booking


def _assign(booking: Booking, technician: User) -> None:
    booking.technician = technician
    booking.status = S.ASSIGNED
    booking.assigned_at = timezone.now()
    booking.save(update_fields=['technician', 'status', 'assigned_at'])
    Conversation.objects.get_or_create(
        customer=booking.customer, counterpart=technician, booking=booking,
        defaults={'kind': Conversation.Kind.BOOKING},
    )
    notify(technician, Notification.Type.JOB, 'New job assigned',
           f'{booking.service_name} ({booking.plan_tag.replace(" Plan", "")}) for a {booking.vehicle_name} at {booking.address}.', booking)
    notify(booking.customer, Notification.Type.BOOKING, 'Technician assigned',
           f'{technician.full_name} will take care of your {booking.service_name}.', booking)


# ------------------------------------------------------------------ technician side

def _require_owner(booking: Booking, technician: User) -> None:
    if booking.technician_id != technician.pk:
        raise PermissionDenied('This job is not assigned to you.')


@transaction.atomic
def start_route(booking: Booking, technician: User) -> Booking:
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    _require_owner(booking, technician)
    _require_status(booking, S.ASSIGNED, message='You can only head out for an assigned job.')
    booking.status = S.ON_THE_WAY
    booking.on_the_way_at = timezone.now()
    booking.save(update_fields=['status', 'on_the_way_at'])
    notify(booking.customer, Notification.Type.ON_THE_WAY, 'Technician on the way',
           f'{technician.full_name} is heading to your location.', booking)
    return booking


@transaction.atomic
def arrive(booking: Booking, technician: User) -> Booking:
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    _require_owner(booking, technician)
    _require_status(booking, S.ON_THE_WAY, S.ASSIGNED, message='Start the trip before marking yourself as arrived.')
    booking.status = S.IN_PROGRESS
    booking.started_at = timezone.now()
    booking.save(update_fields=['status', 'started_at'])
    notify(booking.customer, Notification.Type.ON_THE_WAY, 'Technician has arrived',
           f'{technician.full_name} has arrived and is starting your {booking.service_name}.', booking)
    return booking


def set_checklist_item(booking: Booking, technician: User, item_id: int, done: bool) -> JobChecklistItem:
    _require_owner(booking, technician)
    _require_status(booking, S.IN_PROGRESS, message='Start the job before ticking off steps.')
    item = booking.checklist.filter(pk=item_id).first()
    if not item:
        raise ValidationError({'item': 'That step doesn\'t belong to this job.'})
    item.done = done
    item.done_at = timezone.now() if done else None
    item.save(update_fields=['done', 'done_at'])
    return item


def add_photo(booking: Booking, technician: User, kind: str, image) -> BookingPhoto:
    _require_owner(booking, technician)
    _require_status(booking, S.IN_PROGRESS, message='Start the job before adding photos.')
    if booking.photos.filter(kind=kind).count() >= 10:
        raise ValidationError({'image': 'You can add up to 10 photos in each section.'})
    return BookingPhoto.objects.create(booking=booking, kind=kind, image=image, uploaded_by=technician)


@transaction.atomic
def complete_job(booking: Booking, technician: User, signature_svg: str) -> Booking:
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    _require_owner(booking, technician)
    _require_status(booking, S.IN_PROGRESS, message='Only a job in progress can be completed.')

    problems = {}
    open_steps = booking.checklist.filter(done=False).count()
    if open_steps:
        problems['checklist'] = f'Finish the remaining {open_steps} step{"s" if open_steps != 1 else ""} first.'
    if not booking.photos.filter(kind=BookingPhoto.Kind.BEFORE).exists():
        problems['before_photos'] = 'Add at least one "before" photo.'
    if not booking.photos.filter(kind=BookingPhoto.Kind.AFTER).exists():
        problems['after_photos'] = 'Add at least one "after" photo.'
    if not signature_svg.strip():
        problems['signature'] = 'The customer needs to sign to confirm the service is complete.'
    if problems:
        raise ValidationError(problems)

    now = timezone.now()
    booking.status = S.COMPLETED
    booking.completed_at = now
    booking.signature_svg = signature_svg
    booking.save(update_fields=['status', 'completed_at', 'signature_svg'])

    payout = money(booking.price * Decimal(str(settings.TECHNICIAN_PAYOUT_RATE)))
    Earning.objects.create(
        technician=technician, booking=booking, amount=payout, created_at=now,
        available_at=now + timedelta(hours=EARNING_HOLD_HOURS),
    )
    TechnicianProfile.objects.filter(user=technician).update(jobs_completed=F('jobs_completed') + 1)

    notify(booking.customer, Notification.Type.COMPLETED, 'Service completed',
           f'Your {booking.service_name} is done. Tell us how it went and rate your technician.', booking)
    notify(technician, Notification.Type.PAYMENT, 'Job completed',
           f'You earned ${payout} for {booking.service_name}. It will be available to withdraw in {EARNING_HOLD_HOURS} hours.', booking)
    return booking


def update_location(technician: User, latitude, longitude, heading=0.0) -> TechnicianLocation:
    location, _ = TechnicianLocation.objects.update_or_create(
        technician=technician, defaults={'latitude': latitude, 'longitude': longitude, 'heading': heading}
    )
    return location


# ------------------------------------------------------------------ wallet

def wallet_totals(technician: User) -> dict:
    now = timezone.now()
    open_earnings = Earning.objects.filter(technician=technician, withdrawal__isnull=True)
    available = sum((e.amount for e in open_earnings.filter(available_at__lte=now)), Decimal('0'))
    pending = sum((e.amount for e in open_earnings.filter(available_at__gt=now)), Decimal('0'))
    return {'available': money(available), 'pending': money(pending)}


@transaction.atomic
def withdraw(technician: User, method_label: str = '') -> Withdrawal:
    now = timezone.now()
    earnings = list(
        Earning.objects.select_for_update().filter(technician=technician, withdrawal__isnull=True, available_at__lte=now)
    )
    total = sum((e.amount for e in earnings), Decimal('0'))
    if total <= 0:
        raise StateError('There is nothing available to withdraw yet.')
    withdrawal = Withdrawal.objects.create(technician=technician, amount=money(total), method_label=method_label)
    Earning.objects.filter(pk__in=[e.pk for e in earnings]).update(withdrawal=withdrawal)
    notify(technician, Notification.Type.PAYMENT, 'Withdrawal requested',
           f'${withdrawal.amount} is on its way to {method_label or "your account"} within 1-2 business days.')
    return withdrawal


# ------------------------------------------------------------------ helpers

def _when(booking: Booking) -> str:
    return booking.scheduled_at.strftime('%a, %b %d at %I:%M %p UTC').replace(' 0', ' ')
