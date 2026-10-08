from vehicles.models import Vehicle

from .base import ApiTestCase


class VehicleTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.customer = self.make_customer()
        self.login(self.customer)

    def add(self, plate='ABC1234', **extra):
        data = {'make': 'Toyota', 'model': 'Corolla', 'year': 2016, 'color': 'Blue', 'plate': plate, **extra}
        return self.client.post('/api/v1/vehicles/', data, format='json')

    def test_first_vehicle_becomes_default_and_plate_is_uppercased(self):
        res = self.add(plate=' abc 12 '.replace(' ', ''))
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['plate'], 'ABC12')
        self.assertTrue(res.data['is_default'])
        self.assertEqual(res.data['name'], 'Toyota Corolla')

    def test_making_another_default_unsets_the_first(self):
        first = self.add('AAA111').data
        second = self.add('BBB222').data
        self.assertTrue(first['is_default'])
        self.assertFalse(second['is_default'])
        res = self.client.post(f"/api/v1/vehicles/{second['id']}/make-default/")
        self.assertEqual(res.status_code, 200)
        defaults = list(Vehicle.objects.filter(owner=self.customer, is_default=True).values_list('plate', flat=True))
        self.assertEqual(defaults, ['BBB222'])

    def test_deleting_the_default_promotes_another(self):
        first = self.add('AAA111').data
        self.add('BBB222')
        self.assertEqual(self.client.delete(f"/api/v1/vehicles/{first['id']}/").status_code, 204)
        remaining = Vehicle.objects.get(owner=self.customer)
        self.assertTrue(remaining.is_default)

    def test_duplicate_plate_per_owner_but_not_across_owners(self):
        self.add('AAA111')
        self.assertEqual(self.add('aaa111').status_code, 400)
        self.login(self.make_customer(email='other@example.com'))
        self.assertEqual(self.add('AAA111').status_code, 201)

    def test_validation(self):
        self.assertEqual(self.add(year=1800).status_code, 400)
        self.assertEqual(self.add(year=2999).status_code, 400)
        self.assertEqual(self.add(make='   ').status_code, 400)
        self.assertEqual(self.add(plate='   ').status_code, 400)

    def test_you_only_see_and_touch_your_own(self):
        mine = self.add('AAA111').data
        self.login(self.make_customer(email='other@example.com'))
        self.assertEqual(self.client.get('/api/v1/vehicles/').data['count'], 0)
        self.assertEqual(self.client.get(f"/api/v1/vehicles/{mine['id']}/").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/v1/vehicles/{mine['id']}/").status_code, 404)

    def test_technicians_cannot_use_vehicles(self):
        self.login(self.make_technician())
        self.assertEqual(self.client.get('/api/v1/vehicles/').status_code, 403)

    def test_update(self):
        vehicle = self.add('AAA111').data
        res = self.client.patch(f"/api/v1/vehicles/{vehicle['id']}/", {'color': 'Red', 'notes': 'scratch on door'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['color'], 'Red')

    def test_options(self):
        res = self.client.get('/api/v1/vehicles/options/')
        self.assertEqual(res.status_code, 200)
        self.assertIn('Corolla', res.data['makes']['Toyota'])
        self.assertIn('Black', res.data['colors'])
        self.assertEqual(res.data['years'], sorted(res.data['years'], reverse=True))


class ServiceTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login(self.make_customer())

    def test_list_has_from_price_and_five_services(self):
        res = self.client.get('/api/v1/services/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['count'], 5)
        wash = next(s for s in res.data['results'] if s['slug'] == 'exterior-wash-shine')
        self.assertEqual(wash['from_price'], '79.00')
        self.assertEqual(wash['category_label'], 'Exterior')

    def test_filter_by_category_and_search(self):
        polish = self.client.get('/api/v1/services/?category=polish').data
        self.assertEqual({s['slug'] for s in polish['results']}, {'premium-detail', 'paint-correction'})
        self.assertEqual(self.client.get('/api/v1/services/?category=wheels').data['count'], 0)
        self.assertEqual(self.client.get('/api/v1/services/?category=all').data['count'], 5)
        found = self.client.get('/api/v1/services/?q=ceramic').data
        self.assertEqual([s['slug'] for s in found['results']], ['ceramic-coating'])

    def test_detail_has_plans_with_durations_and_details(self):
        from services.models import Service

        service = Service.objects.get(slug='exterior-wash-shine')
        res = self.client.get(f'/api/v1/services/{service.pk}/')
        self.assertEqual(res.status_code, 200)
        plans = res.data['plans']
        self.assertEqual([p['price'] for p in plans], ['79.00', '129.00', '199.00'])
        self.assertEqual([p['duration'] for p in plans], ['1.5 hours', '2 - 3 hours', '4 - 5 hours'])
        self.assertIn('Tire cleaning & shine', res.data['details'])

    def test_categories(self):
        res = self.client.get('/api/v1/services/categories/')
        self.assertEqual(res.data[0], {'value': 'all', 'label': 'All Services'})
        self.assertEqual(len(res.data), 8)

    def test_inactive_services_are_hidden(self):
        from services.models import Service

        Service.objects.filter(slug='ceramic-coating').update(is_active=False)
        self.assertEqual(self.client.get('/api/v1/services/').data['count'], 4)
