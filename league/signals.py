from django.db.models import Q
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Transfer, Result, PlayerScore, Fixture, TeamMembership
from .services import apply_transfer_memberships, recalculate_fixture_totals, rebuild_scope_materialized


@receiver(post_save, sender=Transfer)
def transfer_saved(sender, instance: Transfer, created: bool, **kwargs):
    apply_transfer_memberships(instance.id)
    # After any transfer, rebuild all scopes in the same season (safe but can be heavy if season is huge)
    scope_ids = instance.season.scopes.values_list("id", flat=True)
    for sid in scope_ids:
        rebuild_scope_materialized(sid)


def _rebuild_related_scope_by_fixture_id(fixture_id: int):
    try:
        fx = Fixture.objects.select_related("scope").get(pk=fixture_id)
    except Fixture.DoesNotExist:
        return
    rebuild_scope_materialized(fx.scope_id)


def _active_player_ids_for_team_at_date(*, season_id: int, team_id: int, date):
    # Active membership window: start_date <= date <= end_date (or end_date is null)
    return (
        TeamMembership.objects
        .filter(season_id=season_id, team_id=team_id, start_date__lte=date)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=date))
        .select_related("player")
        .order_by("player__name")
        .values_list("player_id", flat=True)
    )


def _ensure_default_player_scores(result: Result):
    """Create zero-point PlayerScore rows (3 HOME + 3 AWAY) based on memberships at fixture date.

    - Only creates missing rows (does not delete/overwrite existing).
    - Uses bulk_create (no PlayerScore signals fired) then totals are recalculated once.
    """
    fixture = (
        Fixture.objects
        .select_related("scope__season", "home_team", "away_team")
        .get(pk=result.fixture_id)
    )
    season_id = fixture.scope.season_id
    d = fixture.kickoff_at.date()

    to_create = []

    for side, team_id in ((PlayerScore.HOME, fixture.home_team_id), (PlayerScore.AWAY, fixture.away_team_id)):
        existing = set(
            PlayerScore.objects.filter(result_id=result.id, side=side)
            .values_list("player_id", flat=True)
        )
        player_ids = list(_active_player_ids_for_team_at_date(season_id=season_id, team_id=team_id, date=d)[:3])

        for pid in player_ids:
            if pid in existing:
                continue
            to_create.append(PlayerScore(result_id=result.id, side=side, player_id=pid, points=0))

    if to_create:
        PlayerScore.objects.bulk_create(to_create, ignore_conflicts=True)


@receiver(post_save, sender=Result)
def result_saved(sender, instance: Result, created: bool, **kwargs):
    # On first creation: auto-seed PlayerScore rows so admin shows players immediately.
    if created:
        _ensure_default_player_scores(instance)

    recalculate_fixture_totals(instance.fixture_id)
    _rebuild_related_scope_by_fixture_id(instance.fixture_id)


@receiver(post_delete, sender=Result)
def result_deleted(sender, instance: Result, **kwargs):
    recalculate_fixture_totals(instance.fixture_id)
    _rebuild_related_scope_by_fixture_id(instance.fixture_id)


@receiver(post_save, sender=PlayerScore)
def player_score_saved(sender, instance: PlayerScore, **kwargs):
    recalculate_fixture_totals(instance.result.fixture_id)
    _rebuild_related_scope_by_fixture_id(instance.result.fixture_id)


@receiver(post_delete, sender=PlayerScore)
def player_score_deleted(sender, instance: PlayerScore, **kwargs):
    recalculate_fixture_totals(instance.result.fixture_id)
    _rebuild_related_scope_by_fixture_id(instance.result.fixture_id)
