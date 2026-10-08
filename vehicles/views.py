from datetime import date

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from users.permissions import IsCustomer

from .models import Vehicle
from .serializers import VehicleSerializer

# Choices for the Add Vehicle form. Kept here so the app and the server agree.
MODELS_BY_MAKE = {
    'BMW': ['M4 Series', '3 Series', '5 Series', 'X3', 'X5', 'M3'],
    'Hyundai': ['Creta', 'Elantra', 'Tucson', 'Santa Fe', 'i20', 'Venue'],
    'Toyota': ['Corolla', 'Camry', 'Supra', 'RAV4', 'Land Cruiser', 'Yaris'],
    'Honda': ['Civic', 'Accord', 'CR-V', 'City', 'HR-V'],
    'Volvo': ['XC40', 'XC60', 'XC90', 'S60', 'S90', 'V60'],
    'Mercedes': ['C-Class', 'E-Class', 'S-Class', 'GLC', 'GLE', 'A-Class'],
    'Audi': ['A3', 'A4', 'A6', 'Q3', 'Q5', 'Q7'],
    'Ford': ['Focus', 'Mustang', 'Explorer', 'F-150', 'Fiesta'],
    'Kia': ['Seltos', 'Sportage', 'Sorento', 'Rio', 'Carnival'],
    'Nissan': ['Altima', 'Sentra', 'Rogue', 'X-Trail', 'Patrol'],
}
COLORS = ['Black', 'White', 'Silver', 'Grey', 'Red', 'Blue', 'Green', 'Orange', 'Yellow', 'Brown', 'Beige', 'Other']


@extend_schema(tags=['Vehicles'])
class VehicleViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin,
                     mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """The signed-in customer's saved vehicles."""

    serializer_class = VehicleSerializer
    permission_classes = [IsCustomer]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        return Vehicle.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @extend_schema(request=None, responses=VehicleSerializer)
    @action(detail=True, methods=['post'], url_path='make-default')
    def make_default(self, request, pk=None):
        """Use this car by default when booking."""
        vehicle = self.get_object()
        vehicle.is_default = True
        vehicle.save()
        return Response(self.get_serializer(vehicle).data)

    @extend_schema(
        responses={200: OpenApiResponse(description='`{"makes": {...}, "years": [...], "colors": [...]}`')},
        description='Dropdown choices for the Add Vehicle form: models per make, years (newest first) and colours.',
    )
    @action(detail=False, methods=['get'], pagination_class=None)
    def options(self, request):
        latest = date.today().year + 1
        return Response({'makes': MODELS_BY_MAKE, 'years': list(range(latest, 1989, -1)), 'colors': COLORS})
