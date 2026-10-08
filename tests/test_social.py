from notifications.models import DeviceToken, Notification

from .base import ApiTestCase


class NotificationTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_customer()
        for i in range(3):
            Notification.objects.create(user=self.user, type='promo', title=f'Offer {i}', body='Body')
        Notification.objects.create(user=self.make_customer(email='o@example.com'), type='promo', title='Not yours', body='x')
        self.login(self.user)

    def test_list_count_and_filters(self):
        res = self.client.get('/api/v1/notifications/').data
        self.assertEqual(res['count'], 3)
        self.assertEqual(res['results'][0]['title'], 'Offer 2')  # newest first
        self.assertEqual(res['results'][0]['group'], 'Today')
        self.assertEqual(res['results'][0]['time_ago'], 'Just now')
        self.assertEqual(self.client.get('/api/v1/notifications/unread-count/').data, {'unread': 3})

    def test_mark_one_and_all_read(self):
        first = self.client.get('/api/v1/notifications/').data['results'][0]
        self.assertTrue(self.client.post(f"/api/v1/notifications/{first['id']}/read/").data['read'])
        self.assertEqual(self.client.get('/api/v1/notifications/unread-count/').data['unread'], 2)
        self.assertEqual(self.client.get('/api/v1/notifications/?unread=true').data['count'], 2)
        self.assertEqual(self.client.post('/api/v1/notifications/read-all/').data, {'updated': 2})
        self.assertEqual(self.client.get('/api/v1/notifications/unread-count/').data['unread'], 0)

    def test_cannot_read_someone_elses(self):
        theirs = Notification.objects.get(title='Not yours')
        self.assertEqual(self.client.post(f'/api/v1/notifications/{theirs.pk}/read/').status_code, 404)

    def test_device_token_moves_between_accounts(self):
        body = {'token': 'ExponentPushToken[abc]', 'platform': 'android'}
        self.assertEqual(self.client.post('/api/v1/devices/', body, format='json').status_code, 204)
        other = self.make_customer(email='second@example.com')
        self.login(other)
        self.assertEqual(self.client.post('/api/v1/devices/', body, format='json').status_code, 204)
        self.assertEqual(DeviceToken.objects.get(token=body['token']).user, other)
        self.assertEqual(DeviceToken.objects.count(), 1)


class ChatTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.tech = self.make_technician()
        self.customer = self.make_customer()
        self.booking = self.book_and_pay(self.customer)  # assigning a technician opens a chat
        self.login(self.customer)
        self.chat = self.client.get('/api/v1/conversations/').data['results'][0]

    def test_chat_exists_for_both_sides(self):
        self.assertEqual(self.chat['kind'], 'booking')
        self.assertEqual(self.chat['other']['full_name'], 'Tom Tech')
        self.assertEqual(self.chat['subtitle'], 'Exterior Wash & Shine')
        self.login(self.tech)
        mine = self.client.get('/api/v1/conversations/').data['results'][0]
        self.assertEqual(mine['other']['full_name'], 'Cora Customer')

    def test_messages_unread_and_read_receipts(self):
        url = f"/api/v1/conversations/{self.chat['id']}/messages/"
        sent = self.client.post(url, {'text': '  Gate code is 4521  '}, format='json')
        self.assertEqual(sent.status_code, 201, sent.data)
        self.assertEqual(sent.data['text'], 'Gate code is 4521')
        self.assertTrue(sent.data['mine'])

        self.login(self.tech)
        self.assertEqual(self.client.get('/api/v1/conversations/unread-count/').data['unread'], 1)
        listing = self.client.get('/api/v1/conversations/').data['results'][0]
        self.assertEqual(listing['unread'], 1)
        self.assertEqual(listing['last_message']['text'], 'Gate code is 4521')

        messages = self.client.get(url).data
        self.assertEqual([m['text'] for m in messages], ['Gate code is 4521'])
        self.assertFalse(messages[0]['mine'])
        self.assertEqual(self.client.get('/api/v1/conversations/unread-count/').data['unread'], 0)  # opening read it

        self.client.post(url, {'text': 'On my way'}, format='json')
        self.login(self.customer)
        newer = self.client.get(url + f'?after={messages[0]["id"]}').data
        self.assertEqual([m['text'] for m in newer], ['On my way'])

    def test_blank_message_rejected(self):
        url = f"/api/v1/conversations/{self.chat['id']}/messages/"
        self.assertEqual(self.client.post(url, {'text': '   '}, format='json').status_code, 400)

    def test_strangers_cannot_read_or_write(self):
        self.login(self.make_customer(email='stranger@example.com'))
        url = f"/api/v1/conversations/{self.chat['id']}/messages/"
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {'text': 'hi'}, format='json').status_code, 404)

    def test_support_chat(self):
        self.assertEqual(self.client.post('/api/v1/conversations/support/').status_code, 404)  # no staff yet
        from users.models import User

        User.objects.create_user(email='staff@example.com', password='x-Y9z-long-pass', full_name='Sam Support', is_staff=True)
        first = self.client.post('/api/v1/conversations/support/')
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data['other']['full_name'], 'Volvo Support')
        again = self.client.post('/api/v1/conversations/support/')
        self.assertEqual(first.data['id'], again.data['id'])  # same chat, not a new one
