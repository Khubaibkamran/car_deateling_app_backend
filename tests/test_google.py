from unittest import mock

from users.google import GoogleTokenError
from users.models import User

from .base import ApiTestCase

URL = '/api/v1/auth/google/'
VERIFY = 'users.views.verify_google_token'
CLAIMS = {'email': 'New.Person@Gmail.com', 'email_verified': True, 'name': 'New Person'}


class GoogleLoginTests(ApiTestCase):
    def test_new_google_user_gets_a_customer_account(self):
        with mock.patch(VERIFY, return_value=CLAIMS):
            res = self.client.post(URL, {'id_token': 'x'}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertTrue(res.data['created'])
        self.assertEqual(res.data['user']['email'], 'new.person@gmail.com')
        self.assertEqual(res.data['user']['role'], 'customer')
        self.assertIn('access', res.data)
        self.assertFalse(User.objects.get(email='new.person@gmail.com').has_usable_password())

    def test_new_technician_gets_a_profile(self):
        with mock.patch(VERIFY, return_value=CLAIMS):
            res = self.client.post(URL, {'id_token': 'x', 'role': 'technician'}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertTrue(User.objects.get(email='new.person@gmail.com').technician_profile)

    def test_existing_account_signs_in_without_duplicating(self):
        customer = self.make_customer(email='new.person@gmail.com')
        with mock.patch(VERIFY, return_value=CLAIMS):
            res = self.client.post(URL, {'id_token': 'x'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertFalse(res.data['created'])
        self.assertEqual(res.data['user']['id'], customer.pk)
        self.assertEqual(User.objects.filter(email='new.person@gmail.com').count(), 1)

    def test_wrong_role_is_refused(self):
        self.make_customer(email='new.person@gmail.com')
        with mock.patch(VERIFY, return_value=CLAIMS):
            res = self.client.post(URL, {'id_token': 'x', 'role': 'technician'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('role', res.data)

    def test_invalid_token_is_401(self):
        with mock.patch(VERIFY, side_effect=GoogleTokenError('Invalid Google sign-in. Please try again.')):
            res = self.client.post(URL, {'id_token': 'bad'}, format='json')
        self.assertEqual(res.status_code, 401)

    def test_unconfigured_server_refuses(self):
        res = self.client.post(URL, {'id_token': 'x'}, format='json')
        self.assertEqual(res.status_code, 401)
        self.assertIn('not configured', res.data['detail'])

    def test_token_is_required(self):
        self.assertEqual(self.client.post(URL, {}, format='json').status_code, 400)
