from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from users.permissions import IsCustomer, IsTechnician

from . import logic
from .models import Booking, Earning, SavedCard
from .serializers import (
    BookingCreateSerializer,
    BookingSerializer,
    CancelSerializer,
    CardSerializer,
    ChecklistItemSerializer,
    ChecklistToggleSerializer,
    CompleteJobSerializer,
    EarningSerializer,
    JobDetailSerializer,
    JobListSerializer,
    LocationSerializer,
    PaySerializer,
    PhotoSerializer,
    PhotoUploadSerializer,
    RescheduleSerializer,
    ReviewCreateSerializer,
    ReviewSerializer,
    WithdrawalSerializer,
    WithdrawRequestSerializer,
)

S = Booking.Status


def _local_tz(request):
    """The client's time zone from `?tz=America/Los_Angeles`, so "today" and weekdays match their clock."""
    name = request.query_params.get('tz')
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError({'tz': 'Unknown time zone.'})
    return ZoneInfo('UTC')


def _booking_queryset():
    return Booking.objects.select_related('customer', 'technician', 'vehicle', 'service', 'plan').prefetch_related(
        'payments', 'photos', 'checklist', 'service__details'
    )


# ====================================================================== customer

@extend_schema(tags=['Bookings'])
class BookingViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The customer's bookings."""

    serializer_class = BookingSerializer
    permission_classes = [IsCustomer]

    def get_queryset(self):
        qs = _booking_queryset().filter(customer=self.request.user)
        scope = self.request.query_params.get('scope')
        if scope == 'upcoming':
            qs = qs.filter(status__in=[S.PENDING_PAYMENT, S.CONFIRMED, S.ASSIGNED, S.ON_THE_WAY, S.IN_PROGRESS])
        elif scope == 'past':
            qs = qs.filter(status__in=[S.COMPLETED, S.CANCELLED])
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter('scope', str, enum=['upcoming', 'past'], description='Active bookings or finished/cancelled ones.'),
            OpenApiParameter('status', str, description='Exact status filter.'),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=BookingCreateSerializer, responses={201: BookingSerializer})
    def create(self, request):
        """Book a service. The booking waits for payment (`pending_payment`) until you call `pay`."""
        serializer = BookingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = logic.create_booking(request.user, **serializer.validated_data)
        return Response(self._out(booking), status=status.HTTP_201_CREATED)

    def _out(self, booking):
        booking = self.get_queryset().get(pk=booking.pk)
        return BookingSerializer(booking, context=self.get_serializer_context()).data

    @extend_schema(request=PaySerializer, responses=BookingSerializer)
    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        """Pay for the booking with a saved card. On success a technician is assigned if one is free."""
        serializer = PaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = self.get_object()
        card = serializer.validated_data.get('card') or SavedCard.objects.filter(user=request.user).first()
        if not card:
            raise ValidationError({'card': 'Add a payment method first.'})
        logic.pay_booking(booking, card)
        return Response(self._out(booking))

    @extend_schema(request=CancelSerializer, responses=BookingSerializer)
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        logic.cancel_booking(self.get_object(), request.user, serializer.validated_data['reason'])
        return Response(self._out(self.get_object()))

    @extend_schema(request=RescheduleSerializer, responses=BookingSerializer)
    @action(detail=True, methods=['post'])
    def reschedule(self, request, pk=None):
        serializer = RescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        logic.reschedule_booking(self.get_object(), serializer.validated_data['scheduled_at'])
        return Response(self._out(self.get_object()))

    @extend_schema(request=ReviewCreateSerializer, responses={201: ReviewSerializer})
    @action(detail=True, methods=['post'])
    def review(self, request, pk=None):
        """Rate a completed service and its technician."""
        serializer = ReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review = logic.submit_review(self.get_object(), request.user, **serializer.validated_data)
        return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: OpenApiResponse(description='Technician position, distance and arrival estimate.')})
    @action(detail=True, methods=['get'])
    def tracking(self, request, pk=None):
        """Live position of the technician while they travel to you. Poll this every few seconds."""
        return Response(logic.tracking(self.get_object()))


@extend_schema(tags=['Payment methods'])
class CardViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Saved cards. Only the brand, last 4 digits and expiry are stored."""

    serializer_class = CardSerializer
    permission_classes = [IsCustomer]
    pagination_class = None

    def get_queryset(self):
        return SavedCard.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @extend_schema(request=None, responses=CardSerializer)
    @action(detail=True, methods=['post'], url_path='make-default')
    def make_default(self, request, pk=None):
        card = self.get_object()
        card.is_default = True
        card.save()
        return Response(self.get_serializer(card).data)


# ====================================================================== technician

@extend_schema(tags=['Technician jobs'])
class JobViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The jobs assigned to the signed-in technician."""

    permission_classes = [IsTechnician]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = _booking_queryset().filter(technician=self.request.user)
        wanted = self.request.query_params.get('status')
        groups = {
            'upcoming': [S.ASSIGNED],
            'in_progress': [S.ON_THE_WAY, S.IN_PROGRESS],
            'completed': [S.COMPLETED],
        }
        if wanted in groups:
            qs = qs.filter(status__in=groups[wanted])
        # Soonest first for work still to do, newest first for finished jobs.
        return qs.order_by('-scheduled_at' if wanted == 'completed' else 'scheduled_at')

    def get_serializer_class(self):
        return JobListSerializer if self.action == 'list' else JobDetailSerializer

    @extend_schema(parameters=[OpenApiParameter('status', str, enum=['upcoming', 'in_progress', 'completed'])])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def _out(self, job):
        return JobDetailSerializer(self.get_queryset().get(pk=job.pk), context=self.get_serializer_context()).data

    @extend_schema(request=None, responses=JobDetailSerializer)
    @action(detail=True, methods=['post'], url_path='start-route')
    def start_route(self, request, pk=None):
        """Leave for the customer. Notifies them that you are on the way."""
        logic.start_route(self.get_object(), request.user)
        return Response(self._out(self.get_object()))

    @extend_schema(request=None, responses=JobDetailSerializer)
    @action(detail=True, methods=['post'])
    def arrived(self, request, pk=None):
        """You are at the customer's place; the job is now in progress."""
        logic.arrive(self.get_object(), request.user)
        return Response(self._out(self.get_object()))

    @extend_schema(request=ChecklistToggleSerializer, responses=ChecklistItemSerializer)
    @action(detail=True, methods=['patch'], url_path=r'checklist/(?P<item_id>\d+)')
    def checklist(self, request, pk=None, item_id=None):
        """Tick or untick one step."""
        serializer = ChecklistToggleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = logic.set_checklist_item(self.get_object(), request.user, int(item_id), serializer.validated_data['done'])
        return Response(ChecklistItemSerializer(item).data)

    @extend_schema(request={'multipart/form-data': PhotoUploadSerializer}, responses={201: PhotoSerializer})
    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def photos(self, request, pk=None):
        """Upload a `before` or `after` photo (multipart form with `kind` and `image`)."""
        serializer = PhotoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        photo = logic.add_photo(self.get_object(), request.user, **serializer.validated_data)
        return Response(PhotoSerializer(photo, context=self.get_serializer_context()).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=['delete'], url_path=r'photos/(?P<photo_id>\d+)')
    def delete_photo(self, request, pk=None, photo_id=None):
        job = self.get_object()
        if job.status != S.IN_PROGRESS:
            raise logic.StateError('Photos can only be removed while the job is in progress.')
        deleted, _ = job.photos.filter(pk=photo_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT if deleted else status.HTTP_404_NOT_FOUND)

    @extend_schema(request=CompleteJobSerializer, responses=JobDetailSerializer)
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """Finish the job. Needs every step ticked, before and after photos, and the customer's signature."""
        serializer = CompleteJobSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        logic.complete_job(self.get_object(), request.user, serializer.validated_data['signature_svg'])
        return Response(self._out(self.get_object()))


@extend_schema(tags=['Technician jobs'])
class OpenJobsView(generics.ListAPIView):
    """Paid bookings no technician has yet; accept one to make it yours."""

    permission_classes = [IsTechnician]
    serializer_class = JobListSerializer

    def get_queryset(self):
        return _booking_queryset().filter(status=S.CONFIRMED, technician__isnull=True, scheduled_at__gte=timezone.now()).order_by('scheduled_at')


@extend_schema(tags=['Technician jobs'], request=None, responses=JobDetailSerializer)
class AcceptJobView(APIView):
    permission_classes = [IsTechnician]

    def post(self, request, pk):
        booking = generics.get_object_or_404(Booking, pk=pk)
        logic.claim_booking(request.user, booking)
        job = _booking_queryset().get(pk=pk)
        return Response(JobDetailSerializer(job, context={'request': request}).data)


@extend_schema(tags=['Technician jobs'], request=LocationSerializer, responses={204: None})
class LocationView(APIView):
    """Report your current position while travelling so the customer can follow you."""

    permission_classes = [IsTechnician]

    def post(self, request):
        serializer = LocationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        logic.update_location(request.user, **serializer.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=['Technician home'],
    parameters=[OpenApiParameter('tz', str, description='IANA time zone, e.g. America/Los_Angeles (defaults to UTC).')],
    responses={200: OpenApiResponse(description="Today's numbers and the next jobs.")},
)
class DashboardView(APIView):
    """What the technician home screen shows."""

    permission_classes = [IsTechnician]

    def get(self, request):
        tz = _local_tz(request)
        now_local = timezone.now().astimezone(tz)
        start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

        jobs = Booking.objects.filter(technician=request.user)
        earned = Earning.objects.filter(technician=request.user, created_at__gte=start, created_at__lt=end).aggregate(t=Sum('amount'))['t']
        upcoming = _booking_queryset().filter(technician=request.user, status=S.ASSIGNED, scheduled_at__gte=timezone.now()).order_by('scheduled_at')[:5]
        profile = request.user.technician_profile
        return Response({
            'name': request.user.first_name,
            'is_available': profile.is_available,
            'earnings_today': earned or 0,
            'assigned': jobs.filter(status=S.ASSIGNED).count(),
            'in_progress': jobs.filter(status__in=[S.ON_THE_WAY, S.IN_PROGRESS]).count(),
            'completed_today': jobs.filter(status=S.COMPLETED, completed_at__gte=start, completed_at__lt=end).count(),
            'upcoming_jobs': JobListSerializer(upcoming, many=True, context={'request': request}).data,
        })


PERIODS = {'week': 7, 'month': 28}


@extend_schema(
    tags=['Technician wallet'],
    parameters=[
        OpenApiParameter('period', str, enum=list(PERIODS), description='`week` (7 days) or `month` (4 weeks).'),
        OpenApiParameter('tz', str, description='IANA time zone for day boundaries.'),
    ],
    responses={200: OpenApiResponse(description='Balance, totals, chart bars and recent payments.')},
)
class EarningsView(APIView):
    """The Earnings screen: balance, chart for the period and the payments list."""

    permission_classes = [IsTechnician]

    def get(self, request):
        period = request.query_params.get('period', 'week')
        if period not in PERIODS:
            raise ValidationError({'period': 'Use "week" or "month".'})
        tz = _local_tz(request)
        today = timezone.now().astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)

        if period == 'week':
            # Seven bars, one per day, ending today.
            buckets = [(today - timedelta(days=6 - i), today - timedelta(days=5 - i)) for i in range(7)]
            labels = [b[0].strftime('%a') for b in buckets]
        else:
            # Four bars, one per week, ending today.
            buckets = [(today - timedelta(days=27 - 7 * i), today - timedelta(days=20 - 7 * i)) for i in range(4)]
            labels = [f'W{i + 1}' for i in range(4)]
        range_start, range_end = buckets[0][0], buckets[-1][1]

        in_range = list(
            Earning.objects.filter(technician=request.user, created_at__gte=range_start, created_at__lt=range_end)
        )
        bars = [
            {'label': label, 'amount': sum((e.amount for e in in_range if lo <= e.created_at < hi), 0)}
            for label, (lo, hi) in zip(labels, buckets)
        ]
        total = sum((e.amount for e in in_range), 0)
        wallet = logic.wallet_totals(request.user)
        recent = Earning.objects.filter(technician=request.user).select_related('booking__customer')[:20]
        return Response({
            'period': period,
            'total': total,
            'jobs_done': len(in_range),
            'average_per_job': round(total / len(in_range), 2) if in_range else 0,
            'rating': request.user.technician_profile.rating,
            'bars': bars,
            'balance': wallet['available'],
            'pending': wallet['pending'],
            'payments': EarningSerializer(recent, many=True).data,
            'withdrawals': WithdrawalSerializer(request.user.withdrawals.all()[:10], many=True).data,
        })


@extend_schema(tags=['Technician wallet'], request=WithdrawRequestSerializer, responses={201: WithdrawalSerializer})
class WithdrawView(APIView):
    """Withdraw everything that's available (earnings become available 24 hours after the job)."""

    permission_classes = [IsTechnician]

    def post(self, request):
        serializer = WithdrawRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        withdrawal = logic.withdraw(request.user, serializer.validated_data['method_label'])
        return Response(WithdrawalSerializer(withdrawal).data, status=status.HTTP_201_CREATED)
