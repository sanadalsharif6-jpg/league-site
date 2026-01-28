from django.core.management.base import BaseCommand
from django.db import transaction

from league.models import Season, Scope
from league.services import rebuild_scope_materialized


class Command(BaseCommand):
    help = "Recalculate materialized tables for the latest season (safe to run on a schedule)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--season-id",
            type=int,
            default=None,
            help="Optional Season ID. If omitted, uses the latest season by start_date.",
        )
        parser.add_argument(
            "--competition-type",
            type=str,
            default=None,
            help="Optional competition type filter: LEAGUE / CUP / SUPER_CUP.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        season_id = options.get("season_id")
        comp_type = (options.get("competition_type") or "").strip() or None

        if season_id:
            season = Season.objects.get(pk=season_id)
        else:
            season = Season.objects.order_by("-start_date").first()
            if not season:
                self.stdout.write(self.style.WARNING("No seasons found. Nothing to rebuild."))
                return

        scopes = Scope.objects.filter(season=season).select_related("competition", "division", "group")
        if comp_type:
            scopes = scopes.filter(competition__comp_type=comp_type)
        scopes = scopes.order_by("competition__comp_type", "division__order", "group__order")

        self.stdout.write(self.style.WARNING(f"Rebuilding {scopes.count()} scopes for season {season}..."))
        for s in scopes:
            self.stdout.write(f" - {s}")
            rebuild_scope_materialized(s.id)
        self.stdout.write(self.style.SUCCESS("Done."))
