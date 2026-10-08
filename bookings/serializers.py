from decimal import Decimal

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from services.models import ServicePlan
from users.models import User
from vehicles.models import Vehicle

from .models import Booking, BookingPhoto, Earning, JobChecklistItem, Review, SavedCard, Withdrawal


# ---------------------------------------------------------------- shared small pieces

class PersonSerializer(serializers.ModelSerializer):
    """Just enough about the other person on a booking."""

    rating = serializers.SerializerMethodField()
    employee_code = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'full_name', 'photo', 'phone', 'rating', 'employee_code']

    def get_rating(self, obj) -> float | None:
        profile = getattr(obj, 'technician_profile', None)
        return float(profile.rating) if profile and profile.rating_count else None

    def get_employee_code(self, obj) -> str | None:
        profile = getattr(obj, 'technician_profile', None)
        return profile.employee_code if profile else None


class ChecklistItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobChecklistItem
        fields = ['id', 'text', 'done']


class PhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingPhoto
        fields = ['id', 'kind', 'image', 'created_at']


class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ['rating', 'comment', 'created_at']


class VehicleSnapshotSerializer(serializers.Serializer):
    name = serializers.CharField(source='vehicle_name')
    year = serializers.IntegerField(source='vehicle_year')
    color = serializers.CharField(source='vehicle_color')
    plate = serializers.CharField(source='vehicle_plate')
    photo = serializers.SerializerMethodField()

    def get_photo(self, obj) -> str | None:
        vehicle = obj.vehicle
        if vehicle and vehicle.photo:
            request = self.context.get('request')
            return request.build_absolute_uri(vehicle.photo.url) if request else vehicle.photo.url
        return None


def _duration_label(booking: Booking) -> str:
    return booking.plan.duration_label


# ---------------------------------------------------------------- customer view

class BookingSerializer(serializers.ModelSerializer):
    """A booking as the customer sees it."""

    reference = serializers.CharField(read_only=True)
    service = serializers.SerializerMethodField()
    vehicle = VehicleSnapshotSerializer(source='*', read_only=True)
    technician = PersonSerializer(read_only=True)
    requested_technician = PersonSerializer(read_only=True)
    payment = serializers.SerializerMethodField()
    duration = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    can_reschedule = serializers.SerializerMethodField()
    can_review = serializers.SerializerMethodField()
    review = ReviewSerializer(read_only=True)
    before_photos = serializers.SerializerMethodField()
    after_photos = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            'id', 'reference', 'status', 'service', 'plan_tag', 'price', 'duration', 'vehicle',
            'scheduled_at', 'address', 'latitude', 'longitude', 'notes', 'technician', 'requested_technician',
            'payment', 'can_cancel', 'can_reschedule', 'can_review', 'review', 'before_photos', 'after_photos',
            'created_at', 'paid_at', 'completed_at', 'cancelled_at',
        ]
        read_only_fields = fields

    def get_service(self, obj) -> dict:
        return {'id': obj.service_id, 'name': obj.service_name}

    def get_duration(self, obj) -> str:
        return _duration_label(obj)

    def get_payment(self, obj) -> dict | None:
        payment = obj.payments.first()
        return {'status': payment.status, 'method': payment.method_label, 'amount': payment.amount} if payment else None

    def _hours_ok(self, obj) -> bool:
        return (obj.scheduled_at - timezone.now()).total_seconds() >= settings.CHANGE_WINDOW_HOURS * 3600

    def get_can_cancel(self, obj) -> bool:
        if obj.status == Booking.Status.PENDING_PAYMENT:
            return True
        return obj.status in (Booking.Status.CONFIRMED, Booking.Status.ASSIGNED) and self._hours_ok(obj)

    def get_can_reschedule(self, obj) -> bool:
        return obj.status in (Booking.Status.CONFIRMED, Booking.Status.ASSIGNED) and self._hours_ok(obj)

    def get_can_review(self, obj) -> bool:
        return obj.status == Booking.Status.COMPLETED and not hasattr(obj, 'review')

    def _photos(self, obj, kind):
        if obj.status != Booking.Status.COMPLETED:
            return []
        photos = [p for p in obj.photos.all() if p.kind == kind]
        return PhotoSerializer(photos, many=True, context=self.context).data

    def get_before_photos(self, obj):
        return self._photos(obj, BookingPhoto.Kind.BEFORE)

    def get_after_photos(self, obj):
        return self._photos(obj, BookingPhoto.Kind.AFTER)


class BookingCreateSerializer(serializers.Serializer):
    vehicle = serializers.PrimaryKeyRelatedField(queryset=Vehicle.objects.all())
    plan = serializers.PrimaryKeyRelatedField(queryset=ServicePlan.objects.select_related('service'))
    scheduled_at = serializers.DateTimeField(help_text='ISO 8601 with a time zone, e.g. 2026-07-27T10:00:00-07:00')
    address = serializers.CharField(max_length=255)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=Decimal('-90'), max_value=Decimal('90'))
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=Decimal('-180'), max_value=Decimal('180'))
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True, default='')
    technician = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.TECHNICIAN, is_active=True),
        required=False,
        allow_null=True,
        help_text='Book with this technician (see GET /technicians/). Leave out to let us assign one.',
    )

    def validate_address(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Enter the address.')
        return value


class RescheduleSerializer(serializers.Serializer):
    scheduled_at = serializers.DateTimeField()


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')


class PaySerializer(serializers.Serializer):
    card = serializers.PrimaryKeyRelatedField(
        queryset=SavedCard.objects.all(), required=False, help_text='Defaults to your default saved card.'
    )


class ReviewCreateSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')


class CardSerializer(serializers.ModelSerializer):
    label = serializers.CharField(read_only=True)

    class Meta:
        model = SavedCard
        fields = ['id', 'brand', 'last4', 'exp_month', 'exp_year', 'is_default', 'label']
        read_only_fields = ['id', 'label']

    def validate_last4(self, value):
        if not (value.isdigit() and len(value) == 4):
            raise serializers.ValidationError('Enter the last 4 digits of the card.')
        return value

    def validate(self, attrs):
        now = timezone.now()
        year = attrs.get('exp_year')
        month = attrs.get('exp_month')
        if year and month and year * 12 + month < now.year * 12 + now.month:
            raise serializers.ValidationError({'exp_year': 'This card has expired.'})
        return attrs


class TechnicianCardSerializer(serializers.ModelSerializer):
    """A technician as the customer sees them when choosing who to book."""

    employee_code = serializers.CharField(source='technician_profile.employee_code', read_only=True)
    specialty = serializers.CharField(source='technician_profile.specialty', read_only=True)
    experience = serializers.CharField(source='technician_profile.experience', read_only=True)
    rating = serializers.SerializerMethodField()
    rating_count = serializers.IntegerField(source='technician_profile.rating_count', read_only=True)
    jobs_completed = serializers.IntegerField(source='technician_profile.jobs_completed', read_only=True)
    is_free = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'full_name', 'photo', 'bio', 'city', 'employee_code', 'specialty', 'experience',
            'rating', 'rating_count', 'jobs_completed', 'is_free',
        ]
        read_only_fields = fields

    def get_rating(self, obj) -> float | None:
        profile = obj.technician_profile
        return float(profile.rating) if profile.rating_count else None

    def get_is_free(self, obj) -> bool | None:
        """Free at the time asked about with `?scheduled_at=`; null when no time was given."""
        return self.context.get('free_ids', {}).get(obj.pk)


# ---------------------------------------------------------------- technician view

class JobListSerializer(serializers.ModelSerializer):
    """A job as a card in the technician's list."""

    reference = serializers.CharField(read_only=True)
    customer = PersonSerializer(read_only=True)
    service = serializers.SerializerMethodField()
    vehicle = VehicleSnapshotSerializer(source='*', read_only=True)
    duration = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            'id', 'reference', 'status', 'service', 'plan_tag', 'price', 'duration', 'vehicle', 'customer',
            'scheduled_at', 'address', 'latitude', 'longitude', 'thumbnail',
        ]
        read_only_fields = fields

    def get_service(self, obj) -> dict:
        return {'id': obj.service_id, 'name': obj.service_name}

    def get_duration(self, obj) -> str:
        return _duration_label(obj)

    def get_thumbnail(self, obj) -> str | None:
        image = obj.service.image
        if not image:
            return None
        request = self.context.get('request')
        return request.build_absolute_uri(image.url) if request else image.url


class JobDetailSerializer(JobListSerializer):
    """Everything the technician needs on the Job Details / Service Progress screens."""

    payment = serializers.SerializerMethodField()
    service_details = serializers.SerializerMethodField()
    checklist = ChecklistItemSerializer(many=True, read_only=True)
    before_photos = serializers.SerializerMethodField()
    after_photos = serializers.SerializerMethodField()
    earning = serializers.SerializerMethodField()
    notes = serializers.CharField(read_only=True)

    class Meta(JobListSerializer.Meta):
        fields = JobListSerializer.Meta.fields + [
            'notes', 'payment', 'service_details', 'checklist', 'before_photos', 'after_photos', 'earning',
            'on_the_way_at', 'started_at', 'completed_at',
        ]
        read_only_fields = fields

    def get_payment(self, obj) -> dict | None:
        payment = obj.payments.first()
        return {'status': payment.status, 'method': payment.method_label} if payment else None

    def get_service_details(self, obj) -> list:
        return [d.text for d in obj.service.details.all()]

    def _photos(self, obj, kind):
        photos = [p for p in obj.photos.all() if p.kind == kind]
        return PhotoSerializer(photos, many=True, context=self.context).data

    def get_before_photos(self, obj):
        return self._photos(obj, BookingPhoto.Kind.BEFORE)

    def get_after_photos(self, obj):
        return self._photos(obj, BookingPhoto.Kind.AFTER)

    def get_earning(self, obj) -> Decimal | None:
        earning = getattr(obj, 'earning', None)
        return earning.amount if earning else None


class ChecklistToggleSerializer(serializers.Serializer):
    done = serializers.BooleanField()


class PhotoUploadSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=BookingPhoto.Kind.choices)
    image = serializers.ImageField()


class CompleteJobSerializer(serializers.Serializer):
    signature_svg = serializers.CharField(
        help_text='The customer\'s signature as SVG path data. Required.', max_length=200_000, allow_blank=False
    )


class LocationSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=Decimal('-90'), max_value=Decimal('90'))
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=Decimal('-180'), max_value=Decimal('180'))
    heading = serializers.FloatField(required=False, default=0.0)


class EarningSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source='booking.service_name', read_only=True)
    customer = serializers.CharField(source='booking.customer.full_name', read_only=True)
    pending = serializers.SerializerMethodField()

    class Meta:
        model = Earning
        fields = ['id', 'title', 'customer', 'amount', 'created_at', 'available_at', 'pending']

    def get_pending(self, obj) -> bool:
        return obj.is_pending


class WithdrawalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Withdrawal
        fields = ['id', 'amount', 'method_label', 'status', 'requested_at']
        read_only_fields = fields


class WithdrawRequestSerializer(serializers.Serializer):
    method_label = serializers.CharField(max_length=60, required=False, allow_blank=True, default='')
