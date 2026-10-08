from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from users.models import TechnicianProfile, User

DEMO_PASSWORD = 'Volvo12345'

ACCOUNTS = [
    ('customer@volvo.test', 'Demo Customer', User.Role.CUSTOMER),
    ('technician@volvo.test', 'Michel Technician', User.Role.TECHNICIAN),
    ('technician2@volvo.test', 'Alex Wilson', User.Role.TECHNICIAN),
]


class Command(BaseCommand):
    help = 'Create demo customer and technician accounts for trying the API (development only).'

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Demo accounts are only created when DJANGO_DEBUG is on.')
        for email, name, role in ACCOUNTS:
            user, created = User.objects.get_or_create(email=email, defaults={'full_name': name, 'role': role})
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
            if role == User.Role.TECHNICIAN:
                TechnicianProfile.objects.get_or_create(user=user, defaults={'specialty': 'All-round detailer', 'experience': '3–5 years'})
            self.stdout.write(f'{"created" if created else "exists "}  {email}  ({role})')
        self.stdout.write(self.style.SUCCESS(f'Done. Password for new demo accounts: {DEMO_PASSWORD}'))
