from django.core.management.base import BaseCommand

from core.seed import seed_database


class Command(BaseCommand):
    help = "Boshlang'ich ma'lumotlar: hududlar, administrator (ADMIN_PHONE/ADMIN_PASSWORD), namuna ustalar"

    def handle(self, *args, **options):
        seed_database()
        self.stdout.write(self.style.SUCCESS("Tayyor"))
