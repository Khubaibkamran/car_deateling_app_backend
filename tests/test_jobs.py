from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from bookings.models import Booking, Earning

from .base import ApiTestCase, png


class JobFlowTests(ApiTestCase):
    """The whole job from the technician's side, plus what the customer sees along the way."""

    def setUp(self):
        super().setUp()
        self.tech = self.make_technician()
        self.customer = self.make_customer()
        self.booking = self.book_and_pay(self.customer)
        self.id = self.booking['id']
        self.login(self.tech)

    def url(self, tail=''):
        return f'/api/v1/technician/jobs/{self.id}/{tail}'

    def to_in_progress(self):
        self.assertEqual(self.client.post(self.url('start-route/')).status_code, 200)
        self.assertEqual(self.client.post(self.url('arrived/')).status_code, 200)

    def finish_everything(self):
        job = self.client.get(self.url()).data
        for item in job['checklist']:
            self.client.patch(self.url(f"checklist/{item['id']}/"), {'done': True}, format='json')
        self.client.post(self.url('photos/'), {'kind': 'before', 'image': png()}, format='multipart')
        self.client.post(self.url('photos/'), {'kind': 'after', 'image': png()}, format='multipart')

    def test_job_lists_and_detail(self):
        listing = self.client.get('/api/v1/technician/jobs/?status=upcoming').data
        self.assertEqual(listing['count'], 1)
        detail = self.client.get(self.url()).data
        self.assertEqual(detail['customer']['full_name'], 'Cora Customer')
        self.assertEqual(len(detail['checklist']), 6)
        self.assertEqual(detail['payment']['status'], 'paid')
        self.assertIn('Exterior wash & hand polish', detail['service_details'])
        self.assertEqual(self.client.get('/api/v1/technician/jobs/?status=completed').data['count'], 0)

    def test_other_technicians_cannot_see_or_work_the_job(self):
        self.login(self.make_technician(email='other@example.com', name='Other'))
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.client.post(self.url('start-route/')).status_code, 404)

    def test_customers_cannot_use_technician_endpoints(self):
        self.login(self.customer)
        self.assertEqual(self.client.get('/api/v1/technician/jobs/').status_code, 403)
        self.assertEqual(self.client.get('/api/v1/technician/dashboard/').status_code, 403)

    def test_steps_must_happen_in_order(self):
        self.assertEqual(self.client.post(self.url('arrived/')).status_code, 200)  # assigned -> arrived is allowed
        self.assertEqual(self.client.post(self.url('start-route/')).status_code, 409)  # but not back

    def test_cannot_tick_steps_or_add_photos_before_starting(self):
        item = self.client.get(self.url()).data['checklist'][0]
        self.assertEqual(self.client.patch(self.url(f"checklist/{item['id']}/"), {'done': True}, format='json').status_code, 409)
        self.assertEqual(self.client.post(self.url('photos/'), {'kind': 'before', 'image': png()}, format='multipart').status_code, 409)

    def test_customer_is_told_and_can_track(self):
        self.assertEqual(self.client.post(self.url('start-route/')).data['status'], 'on_the_way')
        self.assertTrue(self.customer.notifications.filter(title='Technician on the way').exists())

        self.assertEqual(self.client.post('/api/v1/technician/location/', {'latitude': '34.0836', 'longitude': '-118.4004', 'heading': 180}, format='json').status_code, 204)
        self.login(self.customer)
        track = self.client.get(f'/api/v1/bookings/{self.id}/tracking/').data
        self.assertEqual(track['status'], 'on_the_way')
        self.assertGreater(track['technician_location']['distance_meters'], 1000)
        self.assertGreaterEqual(track['eta_minutes'], 1)

        self.login(self.tech)
        self.client.post(self.url('arrived/'))
        self.assertTrue(self.customer.notifications.filter(title='Technician has arrived').exists())

    def test_location_is_validated(self):
        res = self.client.post('/api/v1/technician/location/', {'latitude': '200', 'longitude': '0'}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_cannot_complete_until_everything_is_done(self):
        self.to_in_progress()
        res = self.client.post(self.url('complete/'), {'signature_svg': 'M 1 1 L 2 2'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(set(res.data), {'checklist', 'before_photos', 'after_photos'})
        self.finish_everything()
        blank = self.client.post(self.url('complete/'), {'signature_svg': '   '}, format='json')
        self.assertEqual(blank.status_code, 400)
        self.assertEqual(self.client.post(self.url('complete/'), {}, format='json').status_code, 400)

    def test_full_job_to_payout(self):
        self.to_in_progress()
        self.finish_everything()
        done = self.client.post(self.url('complete/'), {'signature_svg': 'M 1 1 L 2 2'}, format='json')
        self.assertEqual(done.status_code, 200, done.data)
        self.assertEqual(done.data['status'], 'completed')
        self.assertEqual(len(done.data['before_photos']), 1)
        self.assertEqual(Decimal(str(done.data['earning'])), Decimal('103.20'))  # 80% of $129

        self.tech.technician_profile.refresh_from_db()
        self.assertEqual(self.tech.technician_profile.jobs_completed, 1)
        self.assertTrue(self.customer.notifications.filter(title='Service completed').exists())

        # Can't complete twice.
        self.assertEqual(self.client.post(self.url('complete/'), {'signature_svg': 'M 1 1'}, format='json').status_code, 409)

        # Home numbers
        home = self.client.get('/api/v1/technician/dashboard/').data
        self.assertEqual(home['completed_today'], 1)
        self.assertEqual(Decimal(str(home['earnings_today'])), Decimal('103.20'))
        self.assertEqual(home['assigned'], 0)

        # Earned money is held for 24h, so it's pending and can't be withdrawn yet.
        earnings = self.client.get('/api/v1/technician/earnings/?period=week').data
        self.assertEqual(Decimal(str(earnings['pending'])), Decimal('103.20'))
        self.assertEqual(Decimal(str(earnings['balance'])), Decimal('0.00'))
        self.assertEqual(earnings['jobs_done'], 1)
        self.assertEqual(len(earnings['bars']), 7)
        self.assertEqual(earnings['payments'][0]['pending'], True)
        self.assertEqual(self.client.post('/api/v1/technician/wallet/withdraw/', {}, format='json').status_code, 409)

        # After the hold, it becomes available and can be withdrawn exactly once.
        Earning.objects.update(available_at=timezone.now() - timedelta(minutes=1))
        wallet = self.client.get('/api/v1/technician/earnings/?period=month').data
        self.assertEqual(Decimal(str(wallet['balance'])), Decimal('103.20'))
        self.assertEqual(len(wallet['bars']), 4)
        out = self.client.post('/api/v1/technician/wallet/withdraw/', {'method_label': 'Visa •••• 4242'}, format='json')
        self.assertEqual(out.status_code, 201, out.data)
        self.assertEqual(out.data['amount'], '103.20')
        self.assertEqual(self.client.post('/api/v1/technician/wallet/withdraw/', {}, format='json').status_code, 409)
        self.assertEqual(Decimal(str(self.client.get('/api/v1/technician/earnings/').data['balance'])), Decimal('0.00'))

    def test_customer_can_review_once_after_completion(self):
        self.to_in_progress()
        self.finish_everything()
        self.client.post(self.url('complete/'), {'signature_svg': 'M 1 1 L 2 2'}, format='json')

        self.login(self.customer)
        detail = self.client.get(f'/api/v1/bookings/{self.id}/').data
        self.assertTrue(detail['can_review'])
        self.assertEqual(len(detail['after_photos']), 1)

        res = self.client.post(f'/api/v1/bookings/{self.id}/review/', {'rating': 4, 'comment': 'Great'}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(self.client.post(f'/api/v1/bookings/{self.id}/review/', {'rating': 5}, format='json').status_code, 409)
        self.assertEqual(self.client.post(f'/api/v1/bookings/{self.id}/review/', {'rating': 9}, format='json').status_code, 400)

        self.tech.technician_profile.refresh_from_db()
        self.assertEqual(self.tech.technician_profile.rating_count, 1)
        self.assertEqual(self.tech.technician_profile.rating, Decimal('4.00'))
        self.assertTrue(self.tech.notifications.filter(title__contains='review').exists())

    def test_cannot_review_before_completion(self):
        self.login(self.customer)
        res = self.client.post(f'/api/v1/bookings/{self.id}/review/', {'rating': 5}, format='json')
        self.assertEqual(res.status_code, 409)

    def test_photo_limits_and_removal(self):
        self.to_in_progress()
        first = self.client.post(self.url('photos/'), {'kind': 'before', 'image': png()}, format='multipart')
        self.assertEqual(first.status_code, 201, first.data)
        for _ in range(9):
            self.client.post(self.url('photos/'), {'kind': 'before', 'image': png()}, format='multipart')
        self.assertEqual(self.client.post(self.url('photos/'), {'kind': 'before', 'image': png()}, format='multipart').status_code, 400)
        self.assertEqual(self.client.delete(self.url(f"photos/{first.data['id']}/")).status_code, 204)
        self.assertEqual(self.client.post(self.url('photos/'), {'kind': 'sideways', 'image': png()}, format='multipart').status_code, 400)

    def test_checklist_can_be_unticked_and_foreign_items_rejected(self):
        self.to_in_progress()
        item = self.client.get(self.url()).data['checklist'][0]
        on = self.client.patch(self.url(f"checklist/{item['id']}/"), {'done': True}, format='json')
        self.assertTrue(on.data['done'])
        off = self.client.patch(self.url(f"checklist/{item['id']}/"), {'done': False}, format='json')
        self.assertFalse(off.data['done'])
        self.assertEqual(self.client.patch(self.url('checklist/999999/'), {'done': True}, format='json').status_code, 400)


class OpenJobsTests(ApiTestCase):
    def test_technician_can_claim_an_unassigned_job(self):
        customer = self.make_customer()
        booking = self.book_and_pay(customer)  # nobody to assign yet
        self.assertEqual(booking['status'], 'confirmed')

        tech = self.make_technician()
        self.login(tech)
        pool = self.client.get('/api/v1/technician/open-jobs/').data
        self.assertEqual(pool['count'], 1)
        res = self.client.post(f"/api/v1/technician/open-jobs/{booking['id']}/accept/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['status'], 'assigned')
        self.assertEqual(self.client.get('/api/v1/technician/open-jobs/').data['count'], 0)
        self.assertTrue(customer.notifications.filter(title='Technician assigned').exists())

        # Someone else can't take it now.
        self.login(self.make_technician(email='late@example.com', name='Late'))
        self.assertEqual(self.client.post(f"/api/v1/technician/open-jobs/{booking['id']}/accept/").status_code, 409)

    def test_unavailable_technician_cannot_accept(self):
        booking = self.book_and_pay(self.make_customer())
        self.login(self.make_technician(available=False))
        self.assertEqual(self.client.post(f"/api/v1/technician/open-jobs/{booking['id']}/accept/").status_code, 409)

    def test_cannot_accept_a_job_that_overlaps_your_own(self):
        tech = self.make_technician()
        self.book_and_pay(self.make_customer(email='a@example.com'), hour=10)  # goes to tech
        # Second booking at an overlapping time stays open (tech is busy)...
        second = self.book_and_pay(self.make_customer(email='b@example.com'), hour=11)
        self.assertEqual(second['status'], 'confirmed')
        self.login(tech)
        self.assertEqual(self.client.post(f"/api/v1/technician/open-jobs/{second['id']}/accept/").status_code, 409)

    def test_dashboard_counts(self):
        tech = self.make_technician()
        self.book_and_pay(self.make_customer(email='a@example.com'), days=3)
        self.book_and_pay(self.make_customer(email='b@example.com'), days=5)
        self.login(tech)
        home = self.client.get('/api/v1/technician/dashboard/?tz=America/Los_Angeles').data
        self.assertEqual(home['assigned'], 2)
        self.assertEqual(len(home['upcoming_jobs']), 2)
        self.assertEqual(home['name'], 'Tom')
        self.assertTrue(home['is_available'])
        self.assertEqual(self.client.get('/api/v1/technician/dashboard/?tz=Nowhere/City').status_code, 400)
        self.assertEqual(self.client.get('/api/v1/technician/earnings/?period=year').status_code, 400)
