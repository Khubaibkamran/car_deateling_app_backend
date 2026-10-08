import io
import shutil
import tempfile
from datetime import timedelta

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase

from users.models import TechnicianProfile, User
from vehicles.models import Vehicle

PASSWORD = 'Str0ng-Passw0rd!'
_MEDIA = tempfile.mkdtemp(prefix='volvo-test-media-')


def png(name='photo.png') -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new('RGB', (4, 4), 'orange').save(buffer, 'PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=_MEDIA)
class ApiTestCase(APITestCase):
    """Shared helpers: users, the seeded catalogue and a booking-in-three-days payload."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        call_command('seed_catalog', verbosity=0)

    def setUp(self):
        super().setUp()
        cache.clear()  # forget request counts so API rate limits don't leak between tests

    # ---- people
    def make_customer(self, email='cust@example.com', name='Cora Customer') -> User:
        return User.objects.create_user(email=email, password=PASSWORD, full_name=name, role=User.Role.CUSTOMER)

    def make_technician(self, email='tech@example.com', name='Tom Tech', available=True) -> User:
        user = User.objects.create_user(email=email, password=PASSWORD, full_name=name, role=User.Role.TECHNICIAN)
        TechnicianProfile.objects.create(user=user, is_available=available)
        return user

    def make_vehicle(self, owner: User, plate='ABC1234') -> Vehicle:
        return Vehicle.objects.create(owner=owner, make='Toyota', model='Corolla', year=2016, color='Blue', plate=plate)

    def login(self, user: User):
        self.client.force_authenticate(user)

    # ---- catalogue / booking
    def plan(self, slug='exterior-wash-shine', index=1):
        from services.models import Service

        return Service.objects.get(slug=slug).plans.all()[index]

    def booking_payload(self, vehicle, plan=None, days=3, hour=10, **extra):
        plan = plan or self.plan()
        when = (timezone.now() + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
        return {
            'vehicle': vehicle.pk,
            'plan': plan.pk,
            'scheduled_at': when.isoformat(),
            'address': '1287 N Alpine Drive, Beverly Hills, CA',
            'latitude': '34.073600',
            'longitude': '-118.400400',
            **extra,
        }

    def add_card(self, user, last4='4242'):
        from bookings.models import SavedCard

        return SavedCard.objects.create(user=user, brand='Visa', last4=last4, exp_month=12, exp_year=timezone.now().year + 3)

    def book_and_pay(self, customer, vehicle=None, **payload_extra):
        """Create a booking as `customer` and pay for it. Returns the paid booking's JSON."""
        vehicle = vehicle or self.make_vehicle(customer, plate=f'P{customer.pk}{timezone.now().microsecond % 1000}')
        self.add_card(customer)
        self.login(customer)
        created = self.client.post('/api/v1/bookings/', self.booking_payload(vehicle, **payload_extra), format='json')
        self.assertEqual(created.status_code, 201, created.data)
        paid = self.client.post(f"/api/v1/bookings/{created.data['id']}/pay/", {}, format='json')
        self.assertEqual(paid.status_code, 200, paid.data)
        return paid.data
