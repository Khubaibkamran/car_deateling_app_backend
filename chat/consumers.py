"""Live chat over a WebSocket.

Connect to  ws://<host>/ws/chat/<conversation_id>/?token=<access token>
  - send  {"text": "hello"}                          to post a message
  - receive {"type": "message", "message": {...}}    whenever anyone in the chat posts one
"""
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from users.models import User

from .models import Conversation, Message
from .realtime import group_name, message_payload, save_message

UNAUTHORIZED = 4401
NOT_FOUND = 4404


@database_sync_to_async
def _user_for(token: str):
    try:
        user_id = AccessToken(token)['user_id']
    except (TokenError, KeyError):
        return None
    return User.objects.filter(pk=user_id, is_active=True).first()


@database_sync_to_async
def _conversation_for(user, conversation_id):
    conversation = Conversation.objects.filter(pk=conversation_id).first()
    return conversation if conversation and conversation.includes(user) else None


@database_sync_to_async
def _mark_read(conversation_id, reader_id):
    """Messages the other person sent are read once this person has the chat open."""
    Message.objects.filter(conversation_id=conversation_id, read_at__isnull=True).exclude(sender_id=reader_id).update(
        read_at=timezone.now()
    )


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.conversation_id = int(self.scope['url_route']['kwargs']['conversation_id'])
        query = dict(part.split('=', 1) for part in self.scope['query_string'].decode().split('&') if '=' in part)
        self.user = await _user_for(query.get('token', ''))
        if self.user is None:
            await self.close(code=UNAUTHORIZED)
            return
        if await _conversation_for(self.user, self.conversation_id) is None:
            await self.close(code=NOT_FOUND)
            return
        self.group = group_name(self.conversation_id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await _mark_read(self.conversation_id, self.user.pk)

    async def disconnect(self, code):
        if getattr(self, 'group', None):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        text = str(content.get('text', '')).strip()[:1000]
        if not text:
            await self.send_json({'type': 'error', 'detail': 'Write a message first.'})
            return
        message = await database_sync_to_async(save_message)(self.conversation_id, self.user, text)
        await self.channel_layer.group_send(self.group, {'type': 'chat.message', 'message': message_payload(message)})

    async def chat_message(self, event):
        message = event['message']
        if message['sender_id'] != self.user.pk:
            await _mark_read(self.conversation_id, self.user.pk)
        await self.send_json({'type': 'message', 'message': message})
