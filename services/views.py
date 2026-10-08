from django.db.models import Min, Prefetch, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Service, ServicePlan
from .serializers import ServiceDetailSerializer, ServiceListSerializer


@extend_schema(tags=['Services'])
class ServiceViewSet(viewsets.ReadOnlyModelViewSet):
    """The catalogue of detailing services and their plans."""

    def get_queryset(self):
        qs = (
            Service.objects.filter(is_active=True)
            .annotate(lowest_price=Min('plans__price', filter=Q(plans__is_active=True)))
            .prefetch_related(
                Prefetch('plans', queryset=ServicePlan.objects.filter(is_active=True)),
                'details',
            )
        )
        if self.action == 'list':
            category = self.request.query_params.get('category', '').strip().lower()
            if category and category != 'all':
                qs = qs.filter(category=category)
            search = self.request.query_params.get('q', '').strip()
            if search:
                qs = qs.filter(Q(name__icontains=search) | Q(summary__icontains=search) | Q(description__icontains=search))
        return qs

    def get_serializer_class(self):
        return ServiceListSerializer if self.action == 'list' else ServiceDetailSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter('category', str, description='exterior, interior, polish, ceramic, protection, wheels or specialty'),
            OpenApiParameter('q', str, description='Search in name and description.'),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(responses={200: dict}, description='The category chips shown above the list.')
    @action(detail=False, methods=['get'], pagination_class=None)
    def categories(self, request):
        return Response(
            [{'value': 'all', 'label': 'All Services'}]
            + [{'value': value, 'label': label} for value, label in Service.Category.choices]
        )
