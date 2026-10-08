from django.urls import path

from . import views

urlpatterns = [
    path('notifications/', views.NotificationListView.as_view(), name='notifications'),
    path('notifications/unread-count/', views.UnreadCountView.as_view(), name='notifications-unread'),
    path('notifications/read-all/', views.MarkAllReadView.as_view(), name='notifications-read-all'),
    path('notifications/<int:pk>/read/', views.MarkReadView.as_view(), name='notification-read'),
    path('devices/', views.RegisterDeviceView.as_view(), name='register-device'),
]
