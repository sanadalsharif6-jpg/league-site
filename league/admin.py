from __future__ import annotations

from datetime import timedelta

from django.contrib import admin
from django.utils import timezone
from django.db.models import Q

from .models import (
    Season, Division, Group, Competition, Scope,
    Team, Player, TeamMembership, Transfer,
    Gameweek, Fixture, Result, PlayerScore,
    Stage, Bracket, BracketRound, BracketTie,
    AchievementType, Achievement,
    TeamStanding, PlayerStanding, RecordSnapshot, PowerRanking, HallOfFameEntry,
)
from .services import rebuild_scope_materialized


# =========================
# Basic reference models
# =========================

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
    list_filter = (
        "season", 
        "competition__comp_type",
        "division",
        "group"
        )
    search_fields = ("season_name", "competition_name")


# =========================
# Team / Player
# =========================

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "logo_state")
    search_fields = ("name",)
    list_per_page = 100

    def logo_state(self, obj: Team):
        return "✅" if obj.logo else "—"
    logo_state.short_description = "Logo"


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("name", "photo_state")
    search_fields = ("name",)
    list_per_page = 100

    def photo_state(self, obj: Player):
        return "✅" if obj.photo else "—"
    photo_state.short_description = "Photo"


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ("season", "team", "player", "start_date", "end_date")
    list_filter = (
        "season",
        "team"
         )
    search_fields = ("team_name", "playername", "season_name")
    date_hierarchy = "start_date"
    autocomplete_fields = ("team", "player", "season")
    list_per_page = 100


@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = ("season", "date", "player", "from_team", "to_team")
    list_filter = (
        "season", 
        "date",
        "from_team", 
        "to_team"
         )
    search_fields = ("player_name", "from_teamname", "to_teamname", "season_name")
    date_hierarchy = "date"
    autocomplete_fields = ("season", "player", "from_team", "to_team")
    list_per_page = 100


# =========================
# Gameweeks / Fixtures
# =========================

@admin.register(Gameweek)
class GameweekAdmin(admin.ModelAdmin):
    list_display = ("number", "name")
    search_fields = ("name",)
    ordering = ("number", "id")
    list_per_page = 100


@admin.action(description="Create replay fixtures for selected drawn CUP/SUPER_CUP fixtures")
def create_replays(modeladmin, request, queryset):
    queryset = queryset.select_related(
        "scope__competition", "scope", "gameweek", "home_team", "away_team"
    )
    for f in queryset:
        comp_type = f.scope.competition.comp_type
        if comp_type == Competition.LEAGUE:
            continue
        if not f.is_played:
            continue
        if f.home_total_points != f.away_total_points:
            continue
        if Fixture.objects.filter(replay_of=f).exists():
            continue

        Fixture.objects.create(
            scope=f.scope,
            gameweek=f.gameweek,
            kickoff_at=f.kickoff_at + timedelta(days=7),  # ✅ FIXED (was kaickoff_at)
            home_team=f.home_team,
            away_team=f.away_team,
            replay_of=f,
        )


@admin.register(Fixture)
class FixtureAdmin(admin.ModelAdmin):
    list_display = (
        "id", "kickoff_at", "scope_id", "scope_short", "gameweek",
        "home_team", "away_team",
        "replay_of_id",
        "is_played", "home_total_points", "away_total_points",
    )
    list_filter = (
        "scope__season", "scope__competition", "scope__division", "scope__group",
        "gameweek__number", "is_played"
    )
    search_fields = ("home_team__name", "away_team__name")
    date_hierarchy = "kickoff_at"
    list_per_page = 25

    list_select_related = (
        "scope", "scope__season", "scope__competition", "scope__division", "scope__group",
        "gameweek", "home_team", "away_team", "replay_of"
    )

    def scope_short(self, obj):
        s = obj.scope
        return f"{s.season.name} | {s.competition.comp_type} | {s.division.name} | {s.group.name}"
    scope_short.short_description = "Scope"


# =========================
# Results + Player Scores
# =========================

class PlayerScoreInline(admin.TabularInline):
    model = PlayerScore
    extra = 0
    min_num = 0
    max_num = 6

    # أهم شيء: لا Dropdown لاعبين
    autocomplete_fields = ("player",)

    def get_extra(self, request, obj=None, **kwargs):
        return 0 if obj is None else 6

    def get_min_num(self, request, obj=None, **kwargs):
        return 0 if obj is None else 6

    def get_max_num(self, request, obj=None, **kwargs):
        return 6

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj=obj, **kwargs)

        # على صفحة الإضافة قبل اختيار fixture لا تعرض لاعبين
        if obj is None or not getattr(obj, "fixture_id", None):
            formset.form.base_fields["player"].queryset = Player.objects.none()
            return formset

        fixture = obj.fixture
        kickoff_date = fixture.kickoff_at.date()

        allowed_ids = (
            TeamMembership.objects
            .filter(
                team_id__in=[fixture.home_team_id, fixture.away_team_id],
                season_id=fixture.scope.season_id,  # مهم: فلترة الموسم
                start_date__lte=kickoff_date,
            )
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=kickoff_date))
            .values_list("player_id", flat=True)
        )

        formset.form.base_fields["player"].queryset = (
            Player.objects.filter(id__in=allowed_ids).distinct().order_by("name")
        )
        return formset



@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    inlines = [PlayerScoreInline]

    # مهم: يخلي اختيار الـ fixture سريع وما يحملش قائمة ضخمة
    autocomplete_fields = ("fixture",)

    # مهم: ما يخليش Django يعتمد على __str__ الثقيل في اللستة
    list_display = ("id", "fixture_id", "fixture_short", "updated_at")
    list_select_related = (
        "fixture",
        "fixture__home_team",
        "fixture__away_team",
        "fixture__gameweek",
        "fixture__scope",
        "fixture__scope__season",
        "fixture__scope__competition",
        "fixture__scope__division",
        "fixture__scope__group",
    )
    list_per_page = 25
    search_fields = (
        "fixture__home_team__name",
        "fixture__away_team__name",
        "fixture__scope__season__name",
    )

    def fixture_short(self, obj):
        f = obj.fixture
        return f"GW{f.gameweek.number} | {f.home_team} vs {f.away_team} | {f.kickoff_at:%Y-%m-%d}"
    fixture_short.short_description = "Fixture"

    def get_inline_instances(self, request, obj=None):
        # نفس فكرتك: ما نفتحش الـ inlines إلا بعد ما يصير في Result محفوظ
        if obj is None:
            return []
        return super().get_inline_instances(request, obj=obj)


# =========================
# Achievements
# =========================

@admin.register(AchievementType)
class AchievementTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "is_team", "is_player", "icon_key")
    list_filter = (
        "is_team",
        "is_player"
         )
    search_fields = ("name",)


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = (
        "awarded_at", "season", "achievement_type",
        "team", "player", "scope",
        "fixture", "opponent_team", "opponent_player",
    )
    list_filter = (
        "season",
        "achievement_type",
        "scope__competition",
        "scope__division",
        "scope__group",
    )
    search_fields = ("team_name", "playername", "achievement_typename", "season_name")
    date_hierarchy = "awarded_at"
    list_per_page = 100

    autocomplete_fields = (
        "season", "achievement_type", "team", "player",
        "scope", "fixture", "opponent_team", "opponent_player",
    )


# =========================
# Materialized / standings
# =========================

@admin.register(TeamStanding)
class TeamStandingAdmin(admin.ModelAdmin):
    list_display = (
        "scope", "team", "played", "wins", "draws", "losses",
        "match_points", "total_points", "form_last5", "updated_at"
    )
    list_filter = (
        "scope__season", 
        "scope__competition", 
        "scope__division", 
        "scope__group"
    )
    list_per_page = 100
    actions = ["rebuild_scopes"]
    autocomplete_fields = ("scope", "team")

    @admin.action(description="Rebuild standings/records/power rankings for selected scopes")
    def rebuild_scopes(self, request, queryset):
        scope_ids = sorted(set(queryset.values_list("scope_id", flat=True)))
        for sid in scope_ids:
            rebuild_scope_materialized(sid)


@admin.register(PlayerStanding)
class PlayerStandingAdmin(admin.ModelAdmin):
    list_display = (
        "scope", "player", "matches_played", "total_points",
        "best_match_points", "average_points", "stddev_points", "updated_at"
    )
    list_filter = (
        "scope__season",
        "scope__competition",
        "scope__division", 
        "scope__group"
        )
    list_per_page = 100
    autocomplete_fields = ("scope", "player")


@admin.register(RecordSnapshot)
class RecordSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "scope", "biggest_win_margin", "highest_team_match_score", "highest_player_score",
        "longest_win_streak", "longest_unbeaten_streak", "updated_at"
    )
    list_filter = (
        "scope__season", 
        "scope__competition",
        "scope__division",
        "scope__group"
        )
    autocomplete_fields = ("scope",)


@admin.register(PowerRanking)
class PowerRankingAdmin(admin.ModelAdmin):
    list_display = ("scope", "gameweek", "rank", "team", "score")
    list_filter = (
        "scope__season",
        "scope__competition",
        "scope__division",
        "scope__group", 
        "gameweek__number"
           )
    list_per_page = 100
    autocomplete_fields = ("scope", "gameweek", "team")


@admin.register(HallOfFameEntry)
class HallOfFameEntryAdmin(admin.ModelAdmin):
    list_display = ("season", "player", "created_at")
    list_filter = ("season",)
    search_fields = ("player_name", "season_name", "note")
    list_per_page = 100
    autocomplete_fields = ("season", "player")  

# -------------------------
# Playoffs / Brackets admin
# -------------------------

class BracketTieInline(admin.TabularInline):
    model = BracketTie
    extra = 0
    autocomplete_fields = ("leg1_fixture", "leg2_fixture", "home_winner_from", "away_winner_from", "winner_team")
    fields = ("tie_no", "leg1_fixture", "leg2_fixture", "home_seed", "away_seed", "home_winner_from", "away_winner_from", "winner_team")
    ordering = ("tie_no",)


@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ("name", "scope", "stage_type", "order", "start_gameweek", "end_gameweek", "show_bracket")
    list_filter = ("stage_type", "show_bracket", "scope__season", "scope__competition__comp_type", "scope__division", "scope__group")
    search_fields = ("name", "scope__season__name", "scope__competition__name", "scope__division__name", "scope__group__name")
    autocomplete_fields = ("scope",)
    list_per_page = 100


@admin.register(Bracket)
class BracketAdmin(admin.ModelAdmin):
    list_display = ("__str__", "stage", "teams_count", "two_legs", "created_at")
    list_filter = ("two_legs", "stage__scope__season", "stage__scope__competition__comp_type")
    search_fields = ("title", "stage__name")
    autocomplete_fields = ("stage",)
    list_per_page = 100


@admin.register(BracketRound)
class BracketRoundAdmin(admin.ModelAdmin):
    list_display = ("name", "bracket", "order")
    list_filter = ("bracket__stage__scope__season", "bracket__stage__scope__competition__comp_type")
    search_fields = ("name", "bracket__title", "bracket__stage__name")
    autocomplete_fields = ("bracket",)
    inlines = [BracketTieInline]
    ordering = ("bracket", "order")
    list_per_page = 100
