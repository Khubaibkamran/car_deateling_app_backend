import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from services.models import Service, ServicePlan
from vehicles.models import Vehicle


class Booking(models.Model):
    """One detailing job, from the customer paying for it to the technician finishing it.

    Vehicle and service details are copied onto the booking so history stays correct even if the
    customer later edits or deletes the car, or the catalogue changes.
    """

    class Status(models.TextChoices):
        PENDING_PAYMENT = 'pending_payment', 'Waiting for payment'
        CONFIRMED = 'confirmed', 'Confirmed'          # paid, no technician yet
        ASSIGNED = 'assigned', 'Technician assigned'
        ON_THE_WAY = 'on_the_way', 'Technician on the way'
        IN_PROGRESS = 'in_progress', 'In progress'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

    ACTIVE = (Status.CONFIRMED, Status.ASSIGNED, Status.ON_THE_WAY, Status.IN_PROGRESS)

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='bookings')
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='jobs'
    )
    vehicle = models.ForeignKey(Vehicle, null=True, blank=True, on_delete=models.SET_NULL, related_name='bookings')
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name='bookings')
    plan = models.ForeignKey(ServicePlan, on_delete=models.PROTECT, related_name='bookings')

    # Snapshots
    service_name = models.CharField(max_length=120)
    plan_tag = models.CharField(max_length=60)
    vehicle_name = models.CharField(max_length=130)
    vehicle_year = models.PositiveSmallIntegerField()
    vehicle_color = models.CharField(max_length=40)
    vehicle_plate = models.CharField(max_length=20)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    duration_minutes = models.PositiveSmallIntegerField()

    scheduled_at = models.DateTimeField(db_index=True)
    address = models.CharField(max_length=255)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    notes = models.CharField(max_length=300, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    on_the_way_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=200, blank=True)
    # The customer's signature, as the SVG path data the app draws.
    signature_svg = models.TextField(blank=True)

    class Meta:
        ordering = ['-scheduled_at']
        indexes = [
            models.Index(fields=['technician', 'status']),
            models.Index(fields=['customer', 'status']),
        ]

    def __str__(self) -> str:
        return f'{self.reference} · {self.service_name}'

    @property
    def reference(self) -> str:
        return f'VB-{self.pk:06d}' if self.pk else 'VB-NEW'

    @property
    def ends_at(self):
        return self.scheduled_at + timedelta(minutes=self.duration_minutes)

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE


class Payment(models.Model):
    """Money taken for a booking. `reference` comes from the payment provider."""

    class Status(models.TextChoices):
        PAID = 'paid', 'Paid'
        REFUNDED = 'refunded', 'Refunded'
        FAILED = 'failed', 'Failed'

    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    method_label = models.CharField(max_length=60)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PAID)
    reference = models.CharField(max_length=64, unique=True, default=uuid.uuid4)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'{self.booking.reference} {self.amount} {self.status}'


class SavedCard(models.Model):
    """A customer's saved card. Only display details are stored, never the full number."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cards')
    brand = models.CharField(max_length=20)
    last4 = models.CharField(max_length=4)
    exp_month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    exp_year = models.PositiveSmallIntegerField()
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_default', '-created_at']

    @property
    def label(self) -> str:
        return f'{self.brand} •••• {self.last4}'

    def save(self, *args, **kwargs):
        if not SavedCard.objects.filter(user=self.user).exclude(pk=self.pk).exists():
            self.is_default = True
        super().save(*args, **kwargs)
        if self.is_default:
            SavedCard.objects.filter(user=self.user).exclude(pk=self.pk).update(is_default=False)


class JobChecklistItem(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='checklist')
    text = models.CharField(max_length=200)
    done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']


class BookingPhoto(models.Model):
    class Kind(models.TextChoices):
        BEFORE = 'before', 'Before'
        AFTER = 'after', 'After'

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='photos')
    kind = models.CharField(max_length=10, choices=Kind.choices)
    image = models.ImageField(upload_to='jobs/%Y/%m/')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']


class Review(models.Model):
    """The customer's rating of a finished job."""

    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='review')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews_written')
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='reviews_received'
    )
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class TechnicianLocation(models.Model):
    """Where a technician last reported being; the customer sees it while they are on the way."""

    technician = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='location')
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    heading = models.FloatField(default=0)
    updated_at = models.DateTimeField(auto_now=True)


class Withdrawal(models.Model):
    class Status(models.TextChoices):
        REQUESTED = 'requested', 'Requested'
        PAID = 'paid', 'Paid'

    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='withdrawals')
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    method_label = models.CharField(max_length=60, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED)
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-requested_at']


class Earning(models.Model):
    """What a technician earned from one completed job. It can be withdrawn once `available_at` passes."""

    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='earnings')
    booking = models.OneToOneField(Booking, on_delete=models.PROTECT, related_name='earning')
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    created_at = models.DateTimeField(default=timezone.now)
    available_at = models.DateTimeField()
    withdrawal = models.ForeignKey(Withdrawal, null=True, blank=True, on_delete=models.SET_NULL, related_name='earnings')

    class Meta:
        ordering = ['-created_at']

    @property
    def is_pending(self) -> bool:
        return self.available_at > timezone.now()


def money(value) -> Decimal:
    """Round to cents."""
    return Decimal(value).quantize(Decimal('0.01'))
