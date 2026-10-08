from rest_framework import serializers

from users.models import User

from .models import Conversation, Message


class ParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'full_name', 'photo', 'role']


class MessageSerializer(serializers.ModelSerializer):
    mine = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ['id', 'text', 'created_at', 'read_at', 'mine']
        read_only_fields = fields

    def get_mine(self, obj) -> bool:
        return obj.sender_id == self.context['request'].user.pk


class ConversationSerializer(serializers.ModelSerializer):
    other = serializers.SerializerMethodField()
    subtitle = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ['id', 'kind', 'booking', 'other', 'subtitle', 'last_message', 'unread', 'last_message_at']
        read_only_fields = fields

    def get_other(self, obj) -> dict:
        other = obj.other_party(self.context['request'].user)
        # Support staff are shown under the company name rather than as a person.
        if obj.kind == Conversation.Kind.SUPPORT and other.pk == obj.counterpart_id:
            return {'id': other.pk, 'full_name': 'Volvo Support', 'photo': None, 'role': 'support'}
        return ParticipantSerializer(other, context=self.context).data

    def get_subtitle(self, obj) -> str:
        if obj.kind == Conversation.Kind.SUPPORT:
            return 'We usually reply within an hour'
        return obj.booking.service_name if obj.booking else ''

    def get_last_message(self, obj) -> dict | None:
        message = obj.messages.order_by('-created_at', '-id').first()
        if not message:
            return None
        return {
            'text': message.text,
            'created_at': message.created_at,
            'mine': message.sender_id == self.context['request'].user.pk,
        }

    def get_unread(self, obj) -> int:
        return obj.messages.filter(read_at__isnull=True).exclude(sender=self.context['request'].user).count()


class SendMessageSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=1000)

    def validate_text(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Write a message first.')
        return value
