from rest_framework import serializers

from .models import Service, ServicePlan


class ServicePlanSerializer(serializers.ModelSerializer):
    duration = serializers.CharField(source='duration_label', read_only=True)

    class Meta:
        model = ServicePlan
        fields = ['id', 'tag', 'price', 'duration', 'min_minutes', 'max_minutes', 'description']


class ServiceListSerializer(serializers.ModelSerializer):
    from_price = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)
    category_label = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model = Service
        fields = ['id', 'name', 'slug', 'summary', 'category', 'category_label', 'image', 'rating', 'rating_count', 'from_price']


class ServiceDetailSerializer(ServiceListSerializer):
    plans = serializers.SerializerMethodField()
    details = serializers.SlugRelatedField(many=True, read_only=True, slug_field='text')

    class Meta(ServiceListSerializer.Meta):
        fields = ServiceListSerializer.Meta.fields + ['description', 'plans', 'details']

    def get_plans(self, obj) -> list:
        plans = [p for p in obj.plans.all() if p.is_active]
        return ServicePlanSerializer(plans, many=True, context=self.context).data
