"""Helpers shared by the REST views and the WebSocket consumer so both save and announce messages the same way."""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import Conversation, Message


def group_name(conversation_id) -> str:
    return f'chat_{conversation_id}'


def save_message(conversation_id, sender, text: str) -> Message:
    message = Message.objects.create(conversation_id=conversation_id, sender=sender, text=text)
    Conversation.objects.filter(pk=conversation_id).update(last_message_at=message.created_at)
    return message


def message_payload(message: Message) -> dict:
    """The message as sent over the socket. `mine` depends on who is reading, so the sender's id is sent instead."""
    return {
        'id': message.pk,
        'text': message.text,
        'created_at': message.created_at.isoformat(),
        'read_at': message.read_at.isoformat() if message.read_at else None,
        'sender_id': message.sender_id,
    }


def publish(message: Message) -> None:
    """Tell everyone with the chat open about a message saved through the REST API."""
    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(
            group_name(message.conversation_id), {'type': 'chat.message', 'message': message_payload(message)}
        )
