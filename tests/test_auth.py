from django.core import mail
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import PasswordResetCode, User

from .base import PASSWORD, ApiTestCase


class RegisterAndLoginTests(ApiTestCase):
    def register(self, **extra):
        data = {'email': 'New.User@Example.com', 'password': PASSWORD, 'full_name': 'New User', **extra}
        return self.client.post('/api/v1/auth/register/', data, format='json')

    def test_customer_registers_and_gets_tokens(self):
        res = self.register()
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIn('access', res.data)
        self.assertIn('refresh', res.data)
        self.assertEqual(res.data['user']['role'], 'customer')
        self.assertEqual(res.data['user']['email'], 'new.user@example.com')  # stored lower-case
        self.assertIsNone(res.data['user']['technician'])

    def test_technician_gets_a_profile(self):
        res = self.register(role='technician', phone='555 0101')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertTrue(res.data['user']['technician']['is_available'])
        self.assertTrue(User.objects.get(email='new.user@example.com').technician_profile)

    def test_cannot_register_as_staff_or_unknown_role(self):
        self.assertEqual(self.register(role='admin').status_code, 400)
        self.assertEqual(self.register(is_staff=True).status_code, 201)  # extra field ignored...
        self.assertFalse(User.objects.get(email='new.user@example.com').is_staff)  # ...and not applied

    def test_duplicate_email_is_rejected_case_insensitively(self):
        self.register()
        res = self.client.post('/api/v1/auth/register/', {'email': 'NEW.user@example.com', 'password': PASSWORD, 'full_name': 'Again'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('email', res.data)

    def test_weak_passwords_are_rejected(self):
        for bad in ['short', '12345678', 'password']:
            res = self.register(password=bad)
            self.assertEqual(res.status_code, 400, bad)
            self.assertIn('password', res.data)

    def test_login_with_role_check(self):
        self.make_customer(email='c@example.com')
        ok = self.client.post('/api/v1/auth/login/', {'email': 'C@example.com', 'password': PASSWORD, 'role': 'customer'}, format='json')
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual(ok.data['user']['email'], 'c@example.com')

        wrong_app = self.client.post('/api/v1/auth/login/', {'email': 'c@example.com', 'password': PASSWORD, 'role': 'technician'}, format='json')
        self.assertEqual(wrong_app.status_code, 400)
        self.assertIn('role', wrong_app.data)

    def test_wrong_password_is_401(self):
        self.make_customer(email='c@example.com')
        res = self.client.post('/api/v1/auth/login/', {'email': 'c@example.com', 'password': 'nope'}, format='json')
        self.assertEqual(res.status_code, 401)

    def test_protected_endpoint_needs_a_token(self):
        self.assertEqual(self.client.get('/api/v1/me/').status_code, 401)

    def test_refresh_and_logout_blacklist(self):
        user = self.make_customer()
        refresh = str(RefreshToken.for_user(user))
        new = self.client.post('/api/v1/auth/refresh/', {'refresh': refresh}, format='json')
        self.assertEqual(new.status_code, 200, new.data)
        # Rotation blacklists the old token, so reusing it fails.
        reuse = self.client.post('/api/v1/auth/refresh/', {'refresh': refresh}, format='json')
        self.assertEqual(reuse.status_code, 401)

        self.login(user)
        out = self.client.post('/api/v1/auth/logout/', {'refresh': new.data['refresh']}, format='json')
        self.assertEqual(out.status_code, 204)
        self.assertEqual(self.client.post('/api/v1/auth/refresh/', {'refresh': new.data['refresh']}, format='json').status_code, 401)


class ProfileTests(ApiTestCase):
    def test_me_and_edit(self):
        user = self.make_customer()
        self.login(user)
        self.assertEqual(self.client.get('/api/v1/me/').data['full_name'], 'Cora Customer')
        res = self.client.patch('/api/v1/me/', {'full_name': ' Cora C. ', 'phone': '555', 'city': 'LA', 'bio': 'hi'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['full_name'], 'Cora C.')
        self.assertEqual(res.data['city'], 'LA')

    def test_email_cannot_be_changed_here(self):
        user = self.make_customer()
        self.login(user)
        self.client.patch('/api/v1/me/', {'email': 'hacker@example.com'}, format='json')
        user.refresh_from_db()
        self.assertEqual(user.email, 'cust@example.com')

    def test_empty_name_rejected(self):
        self.login(self.make_customer())
        self.assertEqual(self.client.patch('/api/v1/me/', {'full_name': '   '}, format='json').status_code, 400)

    def test_technician_fields_only_apply_to_technicians(self):
        tech = self.make_technician()
        self.login(tech)
        res = self.client.patch('/api/v1/me/', {'specialty': 'Ceramic coating', 'experience': '6–10 years', 'is_available': False}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['technician']['specialty'], 'Ceramic coating')
        self.assertFalse(res.data['technician']['is_available'])

        customer = self.make_customer()
        self.login(customer)
        res = self.client.patch('/api/v1/me/', {'specialty': 'x'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.data['technician'])

    def test_photo_upload_and_removal(self):
        from .base import png

        user = self.make_customer()
        self.login(user)
        res = self.client.patch('/api/v1/me/', {'photo': png()}, format='multipart')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertTrue(res.data['photo'].startswith('http'))
        res = self.client.patch('/api/v1/me/', {'remove_photo': True}, format='json')
        self.assertIsNone(res.data['photo'])

    def test_change_password(self):
        user = self.make_customer()
        self.login(user)
        bad = self.client.post('/api/v1/me/password/', {'current_password': 'wrong', 'new_password': 'An0ther-Str0ng!'}, format='json')
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post('/api/v1/me/password/', {'current_password': PASSWORD, 'new_password': 'An0ther-Str0ng!'}, format='json')
        self.assertEqual(ok.status_code, 204)
        user.refresh_from_db()
        self.assertTrue(user.check_password('An0ther-Str0ng!'))


class PasswordResetTests(ApiTestCase):
    def forgot(self, email):
        return self.client.post('/api/v1/auth/password/forgot/', {'email': email}, format='json')

    def issued_code(self):
        """The 6-digit code from the email that was just 'sent'."""
        import re

        return re.search(r'\b(\d{6})\b', mail.outbox[-1].body).group(1)

    def test_full_flow(self):
        user = self.make_customer(email='forgot@example.com')
        self.assertEqual(self.forgot('Forgot@Example.com').status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['forgot@example.com'])
        code = self.issued_code()

        verify = self.client.post('/api/v1/auth/password/verify/', {'email': 'forgot@example.com', 'code': code}, format='json')
        self.assertEqual(verify.status_code, 200, verify.data)

        new_password = 'Brand-New-Pass1'
        reset = self.client.post('/api/v1/auth/password/reset/', {'reset_token': verify.data['reset_token'], 'new_password': new_password}, format='json')
        self.assertEqual(reset.status_code, 204, getattr(reset, 'data', None))
        user.refresh_from_db()
        self.assertTrue(user.check_password(new_password))
        login = self.client.post('/api/v1/auth/login/', {'email': 'forgot@example.com', 'password': new_password}, format='json')
        self.assertEqual(login.status_code, 200)

        # The same token can't be used twice.
        again = self.client.post('/api/v1/auth/password/reset/', {'reset_token': verify.data['reset_token'], 'new_password': 'Another-Pass-22'}, format='json')
        self.assertEqual(again.status_code, 400)

    def test_unknown_email_looks_identical_and_sends_nothing(self):
        res = self.forgot('nobody@example.com')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_wrong_code_and_lockout_after_five_tries(self):
        self.make_customer(email='forgot@example.com')
        self.forgot('forgot@example.com')
        real = self.issued_code()
        wrong = '000000' if real != '000000' else '111111'
        for _ in range(PasswordResetCode.MAX_ATTEMPTS):
            res = self.client.post('/api/v1/auth/password/verify/', {'email': 'forgot@example.com', 'code': wrong}, format='json')
            self.assertEqual(res.status_code, 400)
        # Even the right code no longer works: the code is locked.
        res = self.client.post('/api/v1/auth/password/verify/', {'email': 'forgot@example.com', 'code': real}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_new_code_replaces_the_old_one(self):
        self.make_customer(email='forgot@example.com')
        self.forgot('forgot@example.com')
        first = self.issued_code()
        self.forgot('forgot@example.com')
        second = self.issued_code()
        if first != second:
            res = self.client.post('/api/v1/auth/password/verify/', {'email': 'forgot@example.com', 'code': first}, format='json')
            self.assertEqual(res.status_code, 400)
        ok = self.client.post('/api/v1/auth/password/verify/', {'email': 'forgot@example.com', 'code': second}, format='json')
        self.assertEqual(ok.status_code, 200)

    def test_expired_code_is_rejected(self):
        from datetime import timedelta

        from django.utils import timezone

        self.make_customer(email='forgot@example.com')
        self.forgot('forgot@example.com')
        code = self.issued_code()
        PasswordResetCode.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        res = self.client.post('/api/v1/auth/password/verify/', {'email': 'forgot@example.com', 'code': code}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_weak_new_password_and_bad_token(self):
        self.make_customer(email='forgot@example.com')
        self.forgot('forgot@example.com')
        verify = self.client.post('/api/v1/auth/password/verify/', {'email': 'forgot@example.com', 'code': self.issued_code()}, format='json')
        weak = self.client.post('/api/v1/auth/password/reset/', {'reset_token': verify.data['reset_token'], 'new_password': '12345678'}, format='json')
        self.assertEqual(weak.status_code, 400)
        self.assertIn('new_password', weak.data)
        bad = self.client.post('/api/v1/auth/password/reset/', {'reset_token': 'garbage', 'new_password': 'Fine-Passw0rd!'}, format='json')
        self.assertEqual(bad.status_code, 400)

    def test_code_must_be_six_digits(self):
        res = self.client.post('/api/v1/auth/password/verify/', {'email': 'a@b.co', 'code': '12ab'}, format='json')
        self.assertEqual(res.status_code, 400)
