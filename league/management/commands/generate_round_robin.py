from __future__ import annotations

from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from league.models import Scope, Gameweek, Fixture, Team


class Command(BaseCommand):
    help = "Generate round-robin fixtures for a scope. Even number of teams required."

    def add_arguments(self, parser):
        parser.add_argument("--scope-id", type=int, required=True)
        parser.add_argument("--team-ids", type=str, required=True, help="Comma-separated team IDs")
        parser.add_argument("--start-datetime", type=str, required=True, help="ISO datetime e.g. 2026-01-15T20:00:00")
        parser.add_argument("--days-between", type=int, default=7)
        parser.add_argument("--double-round", action="store_true")

    def handle(self, *args, **opts):
        scope_id = opts["scope_id"]
        team_ids = [int(x.strip()) for x in opts["team_ids"].split(",") if x.strip()]
        start_dt = timezone.make_aware(timezone.datetime.fromisoformat(opts["start_datetime"]))
        days_between = int(opts["days_between"])
        double_round = bool(opts["double_round"])

        scope = Scope.objects.get(pk=scope_id)
        teams = list(Team.objects.filter(id__in=team_ids).order_by("id"))
        if len(teams) < 2:
            raise CommandError("Need at least 2 teams.")
        if len(teams) % 2 == 1:
            raise CommandError("Need even number of teams (add BYE team if needed).")

        ids = [t.id for t in teams]
        n = len(ids)
        rounds = n - 1

        fixtures = []
        kickoff = start_dt
        gw_number = 1

        for r in range(rounds):
            gw, _ = Gameweek.objects.get_or_create(scope=scope, number=gw_number, defaults={"name": f"GW{gw_number}"})

            pairs = []
            for i in range(n // 2):
                a = ids[i]
                b = ids[n - 1 - i]
                if r % 2 == 0:
                    home, away = a, b
                else:
                    home, away = b, a
                pairs.append((home, away))

            for (home_id, away_id) in pairs:
                fixtures.append(Fixture(scope=scope, gameweek=gw, kickoff_at=kickoff, home_team_id=home_id, away_team_id=away_id))

            ids = [ids[0]] + [ids[-1]] + ids[1:-1]
            kickoff = kickoff + timedelta(days=days_between)
            gw_number += 1

        if double_round:
            first_half = list(fixtures)
            for r in range(rounds):
                gw, _ = Gameweek.objects.get_or_create(scope=scope, number=gw_number, defaults={"name": f"GW{gw_number}"})
                start_index = r * (n // 2)
                round_pairs = first_half[start_index:start_index + (n // 2)]
                for f in round_pairs:
                    fixtures.append(Fixture(scope=scope, gameweek=gw, kickoff_at=kickoff, home_team_id=f.away_team_id, away_team_id=f.home_team_id))
                kickoff = kickoff + timedelta(days=days_between)
                gw_number += 1

        Fixture.objects.bulk_create(fixtures, batch_size=500)
        self.stdout.write(self.style.SUCCESS(f"Generated {len(fixtures)} fixtures."))
