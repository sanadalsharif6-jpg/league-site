from __future__ import annotations

from datetime import timedelta

from django.contrib import admin
from django.db.models import Q
from django.utils import timezone

from django.forms.models import BaseInlineFormSet

from .models import (
    Season, Division, Group, Competition, Scope,
    Team, Player, TeamMembership, Transfer,
    Gameweek, Fixture, Result, PlayerScore,
    AchievementType, Achievement,
    TeamStanding, PlayerStanding, RecordSnapshot, PowerRanking, HallOfFameEntry,

)
from .services import rebuild_scope_materialized


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date")
    search_fields = ("name",)
    ordering = ("-start_date",)


@admin.register(Division)
class DivisionAdmin(admin.ModelAdmin):
    list_display = ("name", "order")
    ordering = ("order", "name")
    search_fields = ("name",)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "order")
    ordering = ("order", "name")
    search_fields = ("name",)


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ("name", "comp_type")
    list_filter = ("comp_type",)
    search_fields = ("name",)


@admin.register(Scope)
class ScopeAdmin(admin.ModelAdmin):
    list_display = ("season", "competition", "division", "group")
    list_filter = ("season", "competition__comp_type", "division", "group")
    search_fields = ("season__name", "competition__name")


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "logo_state")
    search_fields = ("name",)

    def logo_state(self, obj: Team):
        return "✅" if obj.logo else "—"
    logo_state.short_description = "Logo"


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("name", "photo_state")
    search_fields = ("name",)

    def photo_state(self, obj: Player):
        return "✅" if obj.photo else "—"
    photo_state.short_description = "Photo"


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ("season", "team", "player", "start_date", "end_date")
    list_filter = ("season", "team")
    search_fields = ("team__name", "player__name", "season__name")
    date_hierarchy = "start_date"


@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = ("season", "date", "player", "from_team", "to_team")
    list_filter = ("season", "date", "from_team", "to_team")
    search_fields = ("player__name", "from_team__name", "to_team__name", "season__name")
    date_hierarchy = "date"


@admin.register(Gameweek)
class GameweekAdmin(admin.ModelAdmin):
    list_display = ("number", "name")
    search_fields = ("name",)
    ordering = ("number", "id")


@admin.action(description="Create replay fixtures for selected drawn CUP/SUPER_CUP fixtures")
def create_replays(modeladmin, request, queryset):
    queryset = queryset.select_related("scope__competition", "scope", "gameweek", "home_team", "away_team")
    for f in queryset:
        comp_type = f.scope.competition.comp_type
        if comp_type == Competition.LEAGUE:
            continue
        if not f.is_played:
            continue
        if f.home_total_points != f.away_total_points:
            continue  # not a draw
        if Fixture.objects.filter(replay_of=f).exists():
            continue  # already has replay

        Fixture.objects.create(
            scope=f.scope,
            gameweek=f.gameweek,
            kickoff_at=f.kickoff_at + timedelta(days=7),
            home_team=f.home_team,
            away_team=f.away_team,
            replay_of=f,
        )


@admin.register(Fixture)
class FixtureAdmin(admin.ModelAdmin):
    list_display = (
        "kickoff_at", "scope", "gameweek", "home_team", "away_team",
        "replay_of",
        "is_played", "home_total_points", "away_total_points",
        "home_match_points", "away_match_points"
    )
    list_filter = (
        "scope__season", "scope__competition", "scope__division", "scope__group",
        "gameweek__number", "is_played"
    )
    search_fields = ("home_team__name", "away_team__name", "scope__season__name", "scope__competition__name")
    date_hierarchy = "kickoff_at"
    list_per_page = 50
    actions = [create_replays]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "scope", "gameweek", "home_team", "away_team",
            "scope__season", "scope__competition", "scope__division", "scope__group",
            "replay_of"
        )


class PlayerScoreInline(admin.TabularInline):
    model = PlayerScore
    extra = 0
    min_num = 0
    max_num = 6

    def get_extra(self, request, obj=None, **kwargs):
        if obj is None:
            return 0
        return 6

    def get_min_num(self, request, obj=None, **kwargs):
        if obj is None:
            return 0
        return 6

    def get_max_num(self, request, obj=None, **kwargs):
        return 6

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj=obj, **kwargs)

        if obj is None or not getattr(obj, "fixture_id", None):
            formset.form.base_fields["player"].queryset = Player.objects.none()
            return formset

        fixture = obj.fixture
        allowed_ids = TeamMembership.objects.filter(
            team_id__in=[fixture.home_team_id, fixture.away_team_id]
        ).values_list("player_id", flat=True)

        formset.form.base_fields["player"].queryset = (
            Player.objects.filter(id__in=allowed_ids)
            .distinct()
            .order_by("name")
        )
        return formset


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    inlines = [PlayerScoreInline]

    def add_view(self, request, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_save_and_continue"] = True
        return super().add_view(request, form_url, extra_context=extra_context)

    def get_inline_instances(self, request, obj=None):
        if obj is None:
            return []
        return super().get_inline_instances(request, obj=obj)


@admin.register(AchievementType)
class AchievementTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "is_team", "is_player", "icon_key")
    list_filter = ("is_team", "is_player")
    search_fields = ("name",)


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ("awarded_at", "season", "achievement_type", "team", "player", "scope", "fixture", "opponent_team", "opponent_player")
    list_filter = ("season", "achievement_type", "scope__competition", "scope__division", "scope__group")
    search_fields = ("team__name", "player__name", "achievement_type__name", "season__name")
    date_hierarchy = "awarded_at"



@admin.register(TeamStanding)
class TeamStandingAdmin(admin.ModelAdmin):
    list_display = ("scope", "team", "played", "wins", "draws", "losses", "match_points", "total_points", "form_last5", "updated_at")
    list_filter = ("scope__season", "scope__competition", "scope__division", "scope__group")
    list_per_page = 100
    actions = ["rebuild_scopes"]

    @admin.action(description="Rebuild standings/records/power rankings for selected scopes")
    def rebuild_scopes(self, request, queryset):
        scope_ids = sorted(set(queryset.values_list("scope_id", flat=True)))
        for sid in scope_ids:
            rebuild_scope_materialized(sid)


@admin.register(PlayerStanding)
class PlayerStandingAdmin(admin.ModelAdmin):
    list_display = ("scope", "player", "matches_played", "total_points", "best_match_points", "average_points", "stddev_points", "updated_at")
    list_filter = ("scope__season", "scope__competition", "scope__division", "scope__group")
    list_per_page = 100


@admin.register(RecordSnapshot)
class RecordSnapshotAdmin(admin.ModelAdmin):
    list_display = ("scope", "biggest_win_margin", "highest_team_match_score", "highest_player_score", "longest_win_streak", "longest_unbeaten_streak", "updated_at")
    list_filter = ("scope__season", "scope__competition", "scope__division", "scope__group")


@admin.register(PowerRanking)
class PowerRankingAdmin(admin.ModelAdmin):
    list_display = ("scope", "gameweek", "rank", "team", "score")
    list_filter = ("scope__season", "scope__competition", "scope__division", "scope__group", "gameweek__number")
    list_per_page = 100

@admin.register(HallOfFameEntry)
class HallOfFameEntryAdmin(admin.ModelAdmin):
    list_display = ("season", "player", "created_at")
    list_filter = ("season",)
    search_fields = ("player__name", "season__name", "note")
