from __future__ import annotations

from datetime import timedelta

from django.contrib import admin
from django.utils import timezone

from .models import (
    Season, Division, Group, Competition, Scope,
    Team, Player, TeamMembership, Transfer,
    Gameweek, Fixture, Result, PlayerScore,
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
        "kickoff_at", "scope", "gameweek", "home_team", "away_team",
        "replay_of",
        "is_played", "home_total_points", "away_total_points",
        "home_match_points", "away_match_points"
    )
    list_filter = (
        "scope__season",
        "scope__competition",
        "scope__division", 
        "scope__group",
        "gameweek__number",
        "is_played"
    )
    search_fields = (
        "home_team_name", "away_team_name",
        "scope_seasonname", "scopecompetition_name"
    )
    date_hierarchy = "kickoff_at"
    list_per_page = 50
    actions = [create_replays]

    # بدل dropdowns الثقيلة
    autocomplete_fields = ("scope", "gameweek", "home_team", "away_team", "replay_of")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "scope", "gameweek", "home_team", "away_team",
            "scope_season", "scopecompetition", "scopedivision", "scope_group",
            "replay_of"
        )


# =========================
# Results + Player Scores
# =========================

class PlayerScoreInline(admin.TabularInline):
    model = PlayerScore
    extra = 0
    min_num = 0
    max_num = 6

    # هذا أهم حل للـOOM: بدل dropdown ضخم، نخليها autocomplete
    autocomplete_fields = ("player",)
    fields = ("player", "points")
    ordering = ("id",)

    def get_extra(self, request, obj=None, **kwargs):
        return 0 if obj is None else 6

    def get_min_num(self, request, obj=None, **kwargs):
        return 0 if obj is None else 6

    def get_max_num(self, request, obj=None, **kwargs):
        return 6

    def get_formset(self, request, obj=None, **kwargs):
        """
        فلترة اللاعبين حسب لاعبي الفريقين في هذا الـFixture.
        ملاحظة: تعديل base_fields هنا ممكن يأثر عالمستوى العام،
        لكن بما أننا نستخدمه داخل request واحد وبـautocomplete،
        هذا عملي وآمن في حالتك.
        """
        formset = super().get_formset(request, obj=obj, **kwargs)

        # قبل ما يكون عندنا Result محفوظ ومربوط بـFixture: نخليها فاضية
        if obj is None or not getattr(obj, "fixture_id", None):
            formset.form.base_fields["player"].queryset = Player.objects.none()
            return formset

        fixture = obj.fixture

        # ✅ فلترة لاعبي الفريقين فقط (وأفضل: فلترة على نفس الموسم)
        season_id = fixture.scope.season_id

        allowed_ids = TeamMembership.objects.filter(
            season_id=season_id,
            team_id__in=[fixture.home_team_id, fixture.away_team_id],
        ).values_list("player_id", flat=True)

        formset.form.base_fields["player"].queryset = (
            Player.objects.filter(id__in=allowed_ids)
            .distinct()
            .order_by("name")
        )
        return formset


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    """
    المنطق المطلوب منك:
    - لما تضيف Result: تختار Fixture وتعمل Save and continue editing
    - بعدها فقط يظهر Inline اللاعبين
    """
    inlines = [PlayerScoreInline]

    list_display = ("fixture", "created_at_safe")
    search_fields = ("fixture_home_teamname", "fixtureaway_team_name")
    list_per_page = 50

    autocomplete_fields = ("fixture",)

    def created_at_safe(self, obj):
        # لو عندك created_at في الموديل
        return getattr(obj, "created_at", "—")
    created_at_safe.short_description = "Created"

    def add_view(self, request, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_save_and_continue"] = True
        return super().add_view(request, form_url, extra_context=extra_context)

    def get_inline_instances(self, request, obj=None):
        if obj is None:
            return []
        return super().get_inline_instances(request, obj=obj)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "fixture",
            "fixture_scope", "fixturescopeseason", "fixturescope_competition",
            "fixture_home_team", "fixture_away_team",
            "fixture__gameweek",
        )


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