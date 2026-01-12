from django.core.management.base import BaseCommand
from django.db import transaction

from league.models import Scope
from league.services import rebuild_scope_materialized


class Command(BaseCommand):
    help = "Recalculate standings/records/power rankings for all scopes (or one scope)."

    def add_arguments(self, parser):
        parser.add_argument("--scope-id", type=int, default=None)

    @transaction.atomic
    def handle(self, *args, **options):
        scope_id = options.get("scope_id")
        if scope_id:
            self.stdout.write(self.style.WARNING(f"Rebuilding scope {scope_id}..."))
            rebuild_scope_materialized(scope_id)
            self.stdout.write(self.style.SUCCESS("Done."))
            return

        scopes = Scope.objects.all().order_by("-season__start_date", "competition__comp_type", "division__order", "group__order")
        self.stdout.write(self.style.WARNING(f"Rebuilding {scopes.count()} scopes..."))
        for s in scopes:
            self.stdout.write(f" - {s}")
            rebuild_scope_materialized(s.id)
        self.stdout.write(self.style.SUCCESS("All scopes rebuilt."))
