from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('bookings', views.BookingViewSet, basename='booking')
router.register('cards', views.CardViewSet, basename='card')
router.register('technician/jobs', views.JobViewSet, basename='job')

urlpatterns = [
    path('technician/dashboard/', views.DashboardView.as_view(), name='technician-dashboard'),
    path('technician/open-jobs/', views.OpenJobsView.as_view(), name='open-jobs'),
    path('technician/open-jobs/<int:pk>/accept/', views.AcceptJobView.as_view(), name='accept-job'),
    path('technician/location/', views.LocationView.as_view(), name='technician-location'),
    path('technician/earnings/', views.EarningsView.as_view(), name='technician-earnings'),
    path('technician/wallet/withdraw/', views.WithdrawView.as_view(), name='technician-withdraw'),
] + router.urls
