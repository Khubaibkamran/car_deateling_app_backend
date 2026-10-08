from django.contrib import admin

from .models import Vehicle


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('plate', 'make', 'model', 'year', 'color', 'owner', 'is_default')
    search_fields = ('plate', 'make', 'model', 'owner__email')
    list_filter = ('make', 'is_default')
