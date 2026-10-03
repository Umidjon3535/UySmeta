"""Rasmiy do'konlardagi joriy narxlarni katalogga yig'ish: python manage.py collect_prices [--pages 8]."""

from django.core.management.base import BaseCommand

from core.market_prices import collect


class Command(BaseCommand):
    help = "Internetdagi rasmiy do'konlardan (JSON-LD) texnika narxlarini katalogga yozadi"

    def add_arguments(self, parser):
        parser.add_argument("--pages", type=int, default=8, help="Har kategoriyadan nechta sahifa (20 tadan)")

    def handle(self, *args, **opts):
        result = collect(max_pages=opts["pages"])
        self.stdout.write(f"Yangi: {result['created']}, yangilandi: {result['updated']}, o'tkazib yuborildi: {result['skipped']}")
        for kind, count in sorted(result["kinds"].items()):
            self.stdout.write(f"  {kind}: {count}")
