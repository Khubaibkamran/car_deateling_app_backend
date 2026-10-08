from django.conf import settings
from django.db import models, transaction


class Vehicle(models.Model):
    """A car a customer has saved. One per owner is the default used when booking."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='vehicles')
    make = models.CharField(max_length=60)
    model = models.CharField(max_length=60)
    year = models.PositiveSmallIntegerField()
    color = models.CharField(max_length=40)
    plate = models.CharField(max_length=20)
    notes = models.CharField(max_length=300, blank=True)
    photo = models.ImageField(upload_to='vehicles/%Y/%m/', blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_default', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['owner', 'plate'], name='unique_plate_per_owner'),
        ]

    def __str__(self) -> str:
        return f'{self.name} ({self.plate})'

    @property
    def name(self) -> str:
        return f'{self.make} {self.model}'.strip()

    def save(self, *args, **kwargs):
        self.plate = self.plate.strip().upper()
        with transaction.atomic():
            first = not Vehicle.objects.filter(owner=self.owner).exclude(pk=self.pk).exists()
            if first:
                self.is_default = True
            super().save(*args, **kwargs)
            if self.is_default:
                Vehicle.objects.filter(owner=self.owner).exclude(pk=self.pk).update(is_default=False)

    def delete(self, *args, **kwargs):
        owner_id, was_default = self.owner_id, self.is_default
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            if was_default:
                # Promote the newest remaining car so there's always a default.
                nxt = Vehicle.objects.filter(owner_id=owner_id).order_by('-created_at').first()
                if nxt:
                    Vehicle.objects.filter(pk=nxt.pk).update(is_default=True)
        return result
