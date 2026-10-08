from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import User
from users.permissions import IsCustomer

from .models import Conversation, Message
from .realtime import publish, save_message
from .serializers import ConversationSerializer, MessageSerializer, SendMessageSerializer


def _mine(user):
    return Conversation.objects.filter(Q(customer=user) | Q(counterpart=user)).select_related(
        'customer', 'counterpart', 'booking'
    )


@extend_schema(tags=['Chat'])
class ConversationListView(generics.ListAPIView):
    """Your chats, most recently active first."""

    serializer_class = ConversationSerializer

    def get_queryset(self):
        return _mine(self.request.user)


@extend_schema(tags=['Chat'], request=None, responses={200: ConversationSerializer})
class SupportConversationView(APIView):
    """Open (or get) the chat with the support team."""

    permission_classes = [IsCustomer]

    def post(self, request):
        staff = User.objects.filter(is_staff=True, is_active=True).order_by('id').first()
        if not staff:
            raise NotFound('Support isn\'t available right now.')
        conversation, _ = Conversation.objects.get_or_create(
            customer=request.user, counterpart=staff, booking=None, defaults={'kind': Conversation.Kind.SUPPORT}
        )
        return Response(ConversationSerializer(conversation, context={'request': request}).data)


@extend_schema(tags=['Chat'])
class MessageListCreateView(generics.GenericAPIView):
    """Messages in one chat (oldest first). Send a new one with POST."""

    def get_serializer_class(self):
        return SendMessageSerializer if self.request.method == 'POST' else MessageSerializer

    def _conversation(self):
        conversation = generics.get_object_or_404(Conversation, pk=self.kwargs['pk'])
        if not conversation.includes(self.request.user):
            raise NotFound()  # don't reveal that the chat exists
        return conversation

    @extend_schema(
        parameters=[OpenApiParameter('after', int, description='Only messages after this message id (for polling).')],
        responses=MessageSerializer(many=True),
    )
    def get(self, request, pk):
        conversation = self._conversation()
        # Opening the chat reads what the other person sent.
        conversation.messages.filter(read_at__isnull=True).exclude(sender=request.user).update(read_at=timezone.now())
        messages = conversation.messages.all()
        after = request.query_params.get('after')
        if after and after.isdigit():
            messages = messages.filter(pk__gt=int(after))
        # The newest 100 are plenty for a chat screen.
        recent = list(messages.order_by('-created_at', '-id')[:100])[::-1]
        return Response(MessageSerializer(recent, many=True, context={'request': request}).data)

    @extend_schema(request=SendMessageSerializer, responses={201: MessageSerializer})
    def post(self, request, pk):
        conversation = self._conversation()
        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = save_message(conversation.pk, request.user, serializer.validated_data['text'])
        publish(message)  # anyone with the chat open sees it straight away
        return Response(MessageSerializer(message, context={'request': request}).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=['Chat'], responses={200: OpenApiResponse(description='`{"unread": 3}`')})
class UnreadMessagesView(APIView):
    """Total unread messages across all chats (for a badge on the Messages tab)."""

    def get(self, request):
        count = (
            Message.objects.filter(conversation__in=_mine(request.user), read_at__isnull=True)
            .exclude(sender=request.user)
            .count()
        )
        return Response({'unread': count})
