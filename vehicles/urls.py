from rest_framework.routers import DefaultRouter

from .views import VehicleViewSet

router = DefaultRouter()
router.register('vehicles', VehicleViewSet, basename='vehicle')

urlpatterns = router.urls
