from django.contrib import admin

from .models import Booking, BookingPhoto, Earning, JobChecklistItem, Payment, Review, SavedCard, Withdrawal


class ChecklistInline(admin.TabularInline):
    model = JobChecklistItem
    extra = 0


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ('reference', 'created_at')


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'service_name', 'customer', 'technician', 'scheduled_at', 'status', 'price')
    list_filter = ('status', 'service')
    search_fields = ('customer__email', 'technician__email', 'vehicle_plate', 'address')
    date_hierarchy = 'scheduled_at'
    inlines = [ChecklistInline, PaymentInline]


@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):
    """Mark a withdrawal as paid here once the money has actually been sent."""

    list_display = ('id', 'technician', 'amount', 'status', 'requested_at')
    list_filter = ('status',)


admin.site.register([Review, Earning, SavedCard, BookingPhoto])
