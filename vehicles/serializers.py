from datetime import date

from rest_framework import serializers

from .models import Vehicle

MIN_YEAR = 1950


class VehicleSerializer(serializers.ModelSerializer):
    name = serializers.CharField(read_only=True)

    class Meta:
        model = Vehicle
        fields = ['id', 'name', 'make', 'model', 'year', 'color', 'plate', 'notes', 'photo', 'is_default', 'created_at']
        read_only_fields = ['id', 'name', 'created_at']

    def validate_year(self, value):
        latest = date.today().year + 1
        if not MIN_YEAR <= value <= latest:
            raise serializers.ValidationError(f'Enter a year between {MIN_YEAR} and {latest}.')
        return value

    def validate_plate(self, value):
        value = value.strip().upper()
        if not value:
            raise serializers.ValidationError('Enter the license plate.')
        owner = self.context['request'].user
        clash = Vehicle.objects.filter(owner=owner, plate=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError('You already saved a vehicle with this plate.')
        return value

    def validate(self, attrs):
        for field in ('make', 'model', 'color'):
            if field in attrs:
                attrs[field] = attrs[field].strip()
                if not attrs[field]:
                    raise serializers.ValidationError({field: 'This field is required.'})
        return attrs
