from datetime import timedelta

from django.utils import timezone

from bookings.models import Booking, Payment

from .base import ApiTestCase


class BookingCreationTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.customer = self.make_customer()
        self.vehicle = self.make_vehicle(self.customer)
        self.login(self.customer)

    def create(self, **kwargs):
        return self.client.post('/api/v1/bookings/', self.booking_payload(self.vehicle, **kwargs), format='json')

    def test_creates_a_pending_booking_with_snapshots_and_checklist(self):
        res = self.create()
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['status'], 'pending_payment')
        self.assertEqual(res.data['price'], '129.00')
        self.assertEqual(res.data['service']['name'], 'Exterior Wash & Shine')
        self.assertEqual(res.data['vehicle']['plate'], 'ABC1234')
        self.assertEqual(res.data['duration'], '2 - 3 hours')
        self.assertTrue(res.data['reference'].startswith('VB-'))
        booking = Booking.objects.get(pk=res.data['id'])
        self.assertEqual(booking.checklist.count(), 6)
        self.assertEqual(booking.duration_minutes, 180)

    def test_snapshot_survives_vehicle_deletion(self):
        booking_id = self.create().data['id']
        self.vehicle.delete()
        booking = self.client.get(f'/api/v1/bookings/{booking_id}/').data
        self.assertEqual(booking['vehicle']['name'], 'Toyota Corolla')

    def test_cannot_book_with_someone_elses_vehicle(self):
        other = self.make_vehicle(self.make_customer(email='o@example.com'), plate='ZZZ999')
        res = self.client.post('/api/v1/bookings/', self.booking_payload(other), format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('vehicle', res.data)

    def test_time_rules(self):
        past = self.client.post('/api/v1/bookings/', self.booking_payload(self.vehicle, days=-1), format='json')
        self.assertEqual(past.status_code, 400)
        too_far = self.client.post('/api/v1/bookings/', self.booking_payload(self.vehicle, days=200), format='json')
        self.assertEqual(too_far.status_code, 400)

    def test_validation_of_location(self):
        bad = self.create(latitude='123')
        self.assertEqual(bad.status_code, 400)
        blank = self.create(address='   ')
        self.assertEqual(blank.status_code, 400)

    def test_technicians_cannot_book(self):
        self.login(self.make_technician())
        self.assertEqual(self.client.get('/api/v1/bookings/').status_code, 403)

    def test_list_scopes_and_privacy(self):
        mine = self.create().data
        other = self.make_customer(email='o@example.com')
        self.login(other)
        self.assertEqual(self.client.get('/api/v1/bookings/').data['count'], 0)
        self.assertEqual(self.client.get(f"/api/v1/bookings/{mine['id']}/").status_code, 404)
        self.login(self.customer)
        self.assertEqual(self.client.get('/api/v1/bookings/?scope=upcoming').data['count'], 1)
        self.assertEqual(self.client.get('/api/v1/bookings/?scope=past').data['count'], 0)


class PaymentAndAssignmentTests(ApiTestCase):
    def test_paying_assigns_a_free_technician_and_notifies_everyone(self):
        tech = self.make_technician()
        customer = self.make_customer()
        booking = self.book_and_pay(customer)
        self.assertEqual(booking['status'], 'assigned')
        self.assertEqual(booking['technician']['full_name'], 'Tom Tech')
        self.assertEqual(booking['payment']['status'], 'paid')
        self.assertEqual(booking['payment']['method'], 'Visa •••• 4242')
        self.assertTrue(tech.notifications.filter(title='New job assigned').exists())
        titles = set(customer.notifications.values_list('title', flat=True))
        self.assertTrue({'Booking confirmed', 'Payment received', 'Technician assigned'} <= titles)

    def test_without_a_technician_it_waits_in_the_open_pool(self):
        booking = self.book_and_pay(self.make_customer())
        self.assertEqual(booking['status'], 'confirmed')
        self.assertIsNone(booking['technician'])

    def test_unavailable_technicians_are_skipped(self):
        self.make_technician(available=False)
        self.assertEqual(self.book_and_pay(self.make_customer())['status'], 'confirmed')

    def test_best_rated_technician_wins(self):
        low = self.make_technician(email='low@example.com', name='Low')
        high = self.make_technician(email='high@example.com', name='High')
        high.technician_profile.rating = 4.9
        high.technician_profile.rating_count = 10
        high.technician_profile.save()
        booking = self.book_and_pay(self.make_customer())
        self.assertEqual(booking['technician']['id'], high.pk)
        self.assertNotEqual(booking['technician']['id'], low.pk)

    def test_overlapping_bookings_go_to_different_technicians(self):
        self.make_technician(email='t1@example.com', name='T1')
        self.make_technician(email='t2@example.com', name='T2')
        first = self.book_and_pay(self.make_customer(email='a@example.com'), hour=10)
        second = self.book_and_pay(self.make_customer(email='b@example.com'), hour=11)
        self.assertEqual(first['status'], 'assigned')
        self.assertEqual(second['status'], 'assigned')
        self.assertNotEqual(first['technician']['id'], second['technician']['id'])

    def test_a_busy_technician_is_not_double_booked(self):
        self.make_technician()
        first = self.book_and_pay(self.make_customer(email='a@example.com'), hour=10)
        second = self.book_and_pay(self.make_customer(email='b@example.com'), hour=11)
        self.assertEqual(first['status'], 'assigned')
        self.assertEqual(second['status'], 'confirmed')  # no free technician
        # But a job well after the first is fine for the same technician.
        third = self.book_and_pay(self.make_customer(email='c@example.com'), days=4, hour=10)
        self.assertEqual(third['status'], 'assigned')

    def test_cannot_pay_twice(self):
        customer = self.make_customer()
        booking = self.book_and_pay(customer)
        res = self.client.post(f"/api/v1/bookings/{booking['id']}/pay/", {}, format='json')
        self.assertEqual(res.status_code, 409)
        self.assertEqual(Payment.objects.filter(booking_id=booking['id']).count(), 1)

    def test_paying_needs_a_card_and_it_must_be_yours(self):
        customer = self.make_customer()
        vehicle = self.make_vehicle(customer)
        self.login(customer)
        created = self.client.post('/api/v1/bookings/', self.booking_payload(vehicle), format='json').data
        no_card = self.client.post(f"/api/v1/bookings/{created['id']}/pay/", {}, format='json')
        self.assertEqual(no_card.status_code, 400)
        theirs = self.add_card(self.make_customer(email='o@example.com'))
        res = self.client.post(f"/api/v1/bookings/{created['id']}/pay/", {'card': theirs.pk}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_expired_card_is_declined(self):
        from bookings.models import SavedCard

        customer = self.make_customer()
        vehicle = self.make_vehicle(customer)
        SavedCard.objects.create(user=customer, brand='Visa', last4='1111', exp_month=1, exp_year=timezone.now().year - 1)
        self.login(customer)
        created = self.client.post('/api/v1/bookings/', self.booking_payload(vehicle), format='json').data
        res = self.client.post(f"/api/v1/bookings/{created['id']}/pay/", {}, format='json')
        self.assertEqual(res.status_code, 402)
        self.assertEqual(Booking.objects.get(pk=created['id']).status, 'pending_payment')


class CancelAndRescheduleTests(ApiTestCase):
    def test_cancel_refunds_and_tells_the_technician(self):
        tech = self.make_technician()
        customer = self.make_customer()
        booking = self.book_and_pay(customer)
        res = self.client.post(f"/api/v1/bookings/{booking['id']}/cancel/", {'reason': 'Plans changed'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['status'], 'cancelled')
        self.assertEqual(Payment.objects.get(booking_id=booking['id']).status, 'refunded')
        self.assertTrue(tech.notifications.filter(title='Job cancelled').exists())
        # A cancelled booking can't be cancelled again or paid.
        self.assertEqual(self.client.post(f"/api/v1/bookings/{booking['id']}/cancel/", {}, format='json').status_code, 409)

    def test_too_late_to_cancel_or_reschedule(self):
        customer = self.make_customer()
        booking = self.book_and_pay(customer)
        Booking.objects.filter(pk=booking['id']).update(scheduled_at=timezone.now() + timedelta(hours=1))
        self.assertEqual(self.client.post(f"/api/v1/bookings/{booking['id']}/cancel/", {}, format='json').status_code, 409)
        later = (timezone.now() + timedelta(days=5)).isoformat()
        self.assertEqual(self.client.post(f"/api/v1/bookings/{booking['id']}/reschedule/", {'scheduled_at': later}, format='json').status_code, 409)
        detail = self.client.get(f"/api/v1/bookings/{booking['id']}/").data
        self.assertFalse(detail['can_cancel'])
        self.assertFalse(detail['can_reschedule'])

    def test_unpaid_booking_can_always_be_cancelled(self):
        customer = self.make_customer()
        vehicle = self.make_vehicle(customer)
        self.login(customer)
        created = self.client.post('/api/v1/bookings/', self.booking_payload(vehicle), format='json').data
        self.assertEqual(self.client.post(f"/api/v1/bookings/{created['id']}/cancel/", {}, format='json').status_code, 200)

    def test_reschedule_keeps_a_free_technician(self):
        tech = self.make_technician()
        customer = self.make_customer()
        booking = self.book_and_pay(customer)
        new_time = (timezone.now() + timedelta(days=6)).replace(hour=15, minute=0, second=0, microsecond=0)
        res = self.client.post(f"/api/v1/bookings/{booking['id']}/reschedule/", {'scheduled_at': new_time.isoformat()}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['status'], 'assigned')
        self.assertEqual(res.data['technician']['id'], tech.pk)

    def test_reschedule_to_a_busy_time_reassigns(self):
        tech = self.make_technician()
        a = self.book_and_pay(self.make_customer(email='a@example.com'), days=3, hour=10)
        b = self.book_and_pay(self.make_customer(email='b@example.com'), days=5, hour=10)
        self.assertEqual((a['status'], b['status']), ('assigned', 'assigned'))
        # Move b onto a's time: the same technician can't do both, so b goes back to the open pool.
        self.login(Booking.objects.get(pk=b['id']).customer)
        clash = Booking.objects.get(pk=a['id']).scheduled_at
        res = self.client.post(f"/api/v1/bookings/{b['id']}/reschedule/", {'scheduled_at': clash.isoformat()}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['status'], 'confirmed')
        self.assertIsNone(res.data['technician'])
        self.assertTrue(tech.notifications.filter(title='Job rescheduled').exists())

    def test_cannot_touch_someone_elses_booking(self):
        booking = self.book_and_pay(self.make_customer())
        self.login(self.make_customer(email='o@example.com'))
        self.assertEqual(self.client.post(f"/api/v1/bookings/{booking['id']}/cancel/", {}, format='json').status_code, 404)
