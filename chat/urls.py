from django.urls import path

from . import views

urlpatterns = [
    path('conversations/', views.ConversationListView.as_view(), name='conversations'),
    path('conversations/support/', views.SupportConversationView.as_view(), name='support-conversation'),
    path('conversations/unread-count/', views.UnreadMessagesView.as_view(), name='messages-unread'),
    path('conversations/<int:pk>/messages/', views.MessageListCreateView.as_view(), name='messages'),
]
