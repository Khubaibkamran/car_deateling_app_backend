from decimal import Decimal

from django.db import models
from django.db.models import Min


class Service(models.Model):
    """A thing we sell, e.g. "Exterior Wash & Shine". It comes in one or more plans."""

    class Category(models.TextChoices):
        EXTERIOR = 'exterior', 'Exterior'
        INTERIOR = 'interior', 'Interior'
        POLISH = 'polish', 'Polish'
        CERAMIC = 'ceramic', 'Ceramic'
        PROTECTION = 'protection', 'Protection'
        WHEELS = 'wheels', 'Wheels'
        SPECIALTY = 'specialty', 'Specialty'

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    summary = models.CharField(max_length=200, blank=True, help_text='One-line text for list cards.')
    category = models.CharField(max_length=20, choices=Category.choices, db_index=True)
    image = models.ImageField(upload_to='services/', blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    # Cached from reviews of bookings for this service.
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal('4.80'))
    rating_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self) -> str:
        return self.name

    @property
    def from_price(self) -> Decimal | None:
        if hasattr(self, 'lowest_price'):  # annotated by the list/detail queryset
            return self.lowest_price
        return self.plans.filter(is_active=True).aggregate(low=Min('price'))['low']


class ServicePlan(models.Model):
    """A tier of a service ("Basic Plan", "Premium Plan") with its own price and length."""

    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='plans')
    tag = models.CharField(max_length=60)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    min_minutes = models.PositiveSmallIntegerField()
    max_minutes = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Leave empty for a fixed length.')
    description = models.CharField(max_length=300, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'price']

    def __str__(self) -> str:
        return f'{self.service.name} – {self.tag}'

    @property
    def duration_label(self) -> str:
        """"45 min", "1.5 hours", "1 hour" or a range like "2 - 3 hours"."""
        low, high = self.min_minutes, self.max_minutes
        if high and high != low:
            if low < 60:
                return f'{low} - {high} min'
            return f'{low / 60:g} - {high / 60:g} hours'
        if low < 60:
            return f'{low} min'
        hours = low / 60
        return f'{hours:g} {"hour" if hours == 1 else "hours"}'

    @property
    def expected_minutes(self) -> int:
        """Longest time the job is expected to take; used to avoid double-booking a technician."""
        return self.max_minutes or self.min_minutes


class ServiceDetail(models.Model):
    """A bullet shown under "Service Details" on the technician's job screen."""

    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='details')
    text = models.CharField(max_length=200)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self) -> str:
        return self.text


class ChecklistTemplateItem(models.Model):
    """A step the technician ticks off; copied onto each booking when it is created."""

    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='checklist')
    text = models.CharField(max_length=200)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self) -> str:
        return self.text
