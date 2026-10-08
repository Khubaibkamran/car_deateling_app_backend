from django.contrib import admin

from .models import ChecklistTemplateItem, Service, ServiceDetail, ServicePlan


class PlanInline(admin.TabularInline):
    model = ServicePlan
    extra = 0


class DetailInline(admin.TabularInline):
    model = ServiceDetail
    extra = 0


class ChecklistInline(admin.TabularInline):
    model = ChecklistTemplateItem
    extra = 0


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'is_active', 'sort_order', 'rating')
    list_filter = ('category', 'is_active')
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}
    inlines = [PlanInline, DetailInline, ChecklistInline]
