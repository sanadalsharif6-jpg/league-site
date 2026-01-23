from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Transfer, Result, PlayerScore, Fixture
from .services import apply_transfer_memberships, recalculate_fixture_totals, rebuild_scope_materialized


@receiver(post_save, sender=Transfer)
def transfer_saved(sender, instance: Transfer, created: bool, **kwargs):
    apply_transfer_memberships(instance.id)
    # بعد أي ترانسفير، الأفضل تحديث كل scopes في نفس الموسم (خفيف عندك لأن الداتا صغيرة)
    scope_ids = instance.season.scopes.values_list("id", flat=True)
    for sid in scope_ids:
        rebuild_scope_materialized(sid)


def _rebuild_related_scope_by_fixture_id(fixture_id: int):
    try:
        fx = Fixture.objects.select_related("scope").get(pk=fixture_id)
    except Fixture.DoesNotExist:
        return
    rebuild_scope_materialized(fx.scope_id)


@receiver(post_save, sender=Result)
def result_saved(sender, instance: Result, **kwargs):
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
