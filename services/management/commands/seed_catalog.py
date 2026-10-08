from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from services.models import ChecklistTemplateItem, Service, ServiceDetail, ServicePlan

DEFAULT_CHECKLIST = [
    'Inspect vehicle and document existing condition',
    'Vacuum seats, mats, and floors',
    'Clean all windows and mirrors',
    'Wash vehicle exterior and wheels',
    'Apply finishing touches and tire shine',
    'Perform final inspection and upload photos',
]

SUMMARY = 'Offer high quality wash to give your car a showroom shine'

# (name, slug, category, description, plans[(tag, price, min, max, description)], details)
CATALOG = [
    (
        'Exterior Wash & Shine', 'exterior-wash-shine', 'exterior',
        "Complete care, inside & out a thorough interior and exterior detail to restore your vehicle's shine",
        [
            ('Basic Plan', '79.00', 90, None, 'Essential exterior & interior cleaning for a fresh, polished finish.'),
            ('Premium Plan', '129.00', 120, 180, 'Deep interior and exterior cleaning for a fresher, more polished look.'),
            ('Premium Plan', '199.00', 240, 300, 'Advanced detailing with a premium finish for a truly refreshed vehicle.'),
        ],
        [
            'Deep interior & exterior detailing',
            'Interior vacuuming & deep cleaning',
            'Exterior wash & hand polish',
            'Tire cleaning & shine',
            'Estimated duration: 2–3 hours',
        ],
    ),
    (
        'Ceramic Coating', 'ceramic-coating', 'ceramic',
        'A long-lasting ceramic layer that protects the paint and keeps it glossy.',
        [
            ('Basic Plan', '249.00', 180, None, 'One-layer ceramic coating with paint prep.'),
            ('Premium Plan', '449.00', 300, 360, 'Multi-layer coating with full paint decontamination.'),
        ],
        ['Paint decontamination', 'Ceramic coating application', 'Hand buffing', 'Cure inspection'],
    ),
    (
        'Premium Detail', 'premium-detail', 'polish',
        'Our most thorough detail for a car that deserves the best.',
        [
            ('Basic Plan', '149.00', 150, None, 'Full interior and exterior detail.'),
            ('Premium Plan', '259.00', 240, 300, 'Full detail with machine polish and paint sealant.'),
        ],
        ['Full interior detail', 'Exterior hand wash', 'Machine polish', 'Paint sealant'],
    ),
    (
        'Interior Deep Clean', 'interior-deep-clean', 'interior',
        'Seats, carpets, dashboard and vents cleaned and refreshed.',
        [
            ('Basic Plan', '59.00', 90, None, 'Vacuum and wipe-down of every surface.'),
            ('Premium Plan', '109.00', 120, 150, 'Shampoo seats and carpets, leather conditioning.'),
        ],
        ['Vacuum seats and floors', 'Shampoo upholstery', 'Dashboard and vents', 'Leather conditioning'],
    ),
    (
        'Paint Correction', 'paint-correction', 'polish',
        'Removes swirls and light scratches to bring back deep gloss.',
        [
            ('Basic Plan', '189.00', 180, None, 'Single-stage correction.'),
            ('Premium Plan', '329.00', 300, 360, 'Multi-stage correction for a mirror finish.'),
        ],
        ['Paint inspection', 'Machine polishing', 'Swirl removal', 'Protective wax'],
    ),
]


class Command(BaseCommand):
    help = 'Create (or update) the service catalogue from the app\'s sample data. Safe to run again.'

    @transaction.atomic
    def handle(self, *args, **options):
        created = 0
        for order, (name, slug, category, description, plans, details) in enumerate(CATALOG):
            service, was_created = Service.objects.update_or_create(
                slug=slug,
                defaults={
                    'name': name, 'category': category, 'description': description,
                    'summary': SUMMARY, 'sort_order': order, 'is_active': True,
                },
            )
            created += was_created

            # Rebuild the child rows so editing this file and re-running keeps the database in sync.
            service.plans.all().delete()
            for i, (tag, price, low, high, plan_text) in enumerate(plans):
                ServicePlan.objects.create(
                    service=service, tag=tag, price=Decimal(price), min_minutes=low, max_minutes=high,
                    description=plan_text, sort_order=i,
                )
            service.details.all().delete()
            for i, text in enumerate(details):
                ServiceDetail.objects.create(service=service, text=text, sort_order=i)
            service.checklist.all().delete()
            for i, text in enumerate(DEFAULT_CHECKLIST):
                ChecklistTemplateItem.objects.create(service=service, text=text, sort_order=i)

        self.stdout.write(self.style.SUCCESS(f'Catalogue ready: {len(CATALOG)} services ({created} new).'))
