from django.apps import AppConfig
from django.db.models.signals import post_migrate


class CoreConfig(AppConfig):
    name = "core"
    verbose_name = "UySmeta"

    def ready(self):
        post_migrate.connect(_run_seed, sender=self)


def _run_seed(sender, **kwargs):
    from .seed import seed_database

    seed_database()
