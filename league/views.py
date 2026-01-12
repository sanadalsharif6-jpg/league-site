from __future__ import annotations
from django.db.models import Q
from django.db import models
from django.db.models import Sum, Count, Q

from collections import defaultdict

from django.shortcuts import render, get_object_or_404
from django.db.models import Prefetch

from .models import (
    Season, Competition, Scope,
    Team, Player, TeamMembership, Transfer,
    Gameweek, Fixture,
    TeamStanding, PlayerStanding,
    AchievementType, Achievement,
)
from .services import head_to_head, player_vs_player
from .utils import sort_standings_with_h2h


def _active_season_competition(request):
    seasons = list(Season.objects.order_by("-start_date"))

    # مهم: نخلي LEAGUE أول خيار افتراضي
    competitions = list(
        Competition.objects.order_by(
            models.Case(
                models.When(comp_type=Competition.LEAGUE, then=models.Value(0)),
                models.When(comp_type=Competition.CUP, then=models.Value(1)),
                models.When(comp_type=Competition.SUPER_CUP, then=models.Value(2)),
                default=models.Value(9),
                output_field=models.IntegerField(),
            ),
            "name",
        )
    )

    season_id = request.GET.get("season")
    comp_id = request.GET.get("competition")

    season = Season.objects.filter(id=season_id).first() if season_id else None
    if not season and seasons:
        season = seasons[0]

    comp = Competition.objects.filter(id=comp_id).first() if comp_id else None
    if not comp and competitions:
        comp = competitions[0]

    return season, comp, seasons, competitions



def home(request):
    season, comp, seasons, competitions = _active_season_competition(request)

    scopes = []
    if season and comp:
        scopes = list(
            Scope.objects.filter(season=season, competition=comp)
            .select_related("season", "competition", "division", "group")
            .order_by("division__order", "group__order")
        )

    context = {
        "season": season,
        "competition": comp,
        "seasons": seasons,
        "competitions": competitions,
        "scopes": scopes,
    }
    return render(request, "league/home.html", context)


def standings(request):
    season, comp, seasons, competitions = _active_season_competition(request)

    league_comp = Competition.objects.filter(comp_type=Competition.LEAGUE).order_by("name").first()
    if not league_comp:
        return render(request, "league/standings.html", {
            "season": season,
            "competition": comp,
            "seasons": seasons,
            "competitions": [],
            "standings_by_scope": [],
        })

    if comp is None or comp.comp_type != Competition.LEAGUE:
        comp = league_comp

    competitions = list(Competition.objects.filter(comp_type=Competition.LEAGUE).order_by("name"))

    scopes = list(
        Scope.objects.filter(season=season, competition=comp)
        .select_related("division", "group", "season", "competition")
        .order_by("division__order", "group__order")
    )

    standings_by_scope = []
    for sc in scopes:
        rows_qs = (
            TeamStanding.objects.filter(scope=sc)
            .select_related("team")
        )

        normalized = []
        for ts in rows_qs:
            normalized.append({
                "team": ts.team,
                "played": ts.played,
                "wins": ts.wins,
                "draws": ts.draws,
                "losses": ts.losses,
                "match_points": ts.match_points,
                "total_points": ts.total_points,
                "form_last5": ts.form_last5,
            })

        # لو sort_standings_with_h2h تتوقع team_id وغيره، خلّيها كما هي عندك أو عدّلها لاحقًا
        # هنا نخلي ترتيب بسيط ثابت (ممكن تخليه نفس ه2h عندك لو تحب)
        normalized.sort(key=lambda r: (-r["match_points"], -r["total_points"], r["team"].name.lower()))

        standings_by_scope.append({"scope": sc, "rows": normalized})

    return render(request, "league/standings.html", {
        "season": season,
        "competition": comp,
        "seasons": seasons,
        "competitions": competitions,
        "standings_by_scope": standings_by_scope,
    })

def players_list(request):
    season, comp, seasons, competitions = _active_season_competition(request)

    scopes = []
    if season and comp:
        scopes = list(Scope.objects.filter(season=season, competition=comp).order_by("division__order", "group__order"))

    # ربط اللاعب بفريقه الحالي في الموسم (Active membership)
    memberships = TeamMembership.objects.filter(season=season, end_date__isnull=True).select_related("player", "team")
    current_team_by_player = {m.player_id: m.team for m in memberships}

    # standing من كل scopes (ممكن اللاعب يظهر في أكثر من scope)
    by_scope = []
    for sc in scopes:
        ps = (
            PlayerStanding.objects.filter(scope=sc)
            .select_related("player")
            .order_by("-total_points", "-average_points", "player__name")
        )
        rows = []
        for row in ps:
            team = current_team_by_player.get(row.player_id)
            rows.append({
                "player": row.player,
                "team": team,
                "total_points": row.total_points,
                "matches_played": row.matches_played,
                "best_match_points": row.best_match_points,
                "average_points": row.average_points,
            })
        by_scope.append({"scope": sc, "rows": rows})

    context = {
        "season": season,
        "competition": comp,
        "seasons": seasons,
        "competitions": competitions,
        "players_by_scope": by_scope,
    }
    return render(request, "league/players.html", context)


def player_detail(request, player_id: int):
    season, comp, seasons, competitions = _active_season_competition(request)
    player = get_object_or_404(Player, pk=player_id)

    # الفريق الحالي
    current_mem = TeamMembership.objects.filter(season=season, player=player, end_date__isnull=True).select_related("team").first()

    # تاريخ الفرق اللي لعب لها في الموسم (طلبك الأخير)
    history = list(
        TeamMembership.objects.filter(season=season, player=player)
        .select_related("team")
        .order_by("start_date")
    )

    transfers = list(
        Transfer.objects.filter(season=season, player=player)
        .select_related("from_team", "to_team")
        .order_by("-date", "-id")
    )

    achievements = list(
        Achievement.objects.filter(season=season, player=player)
        .select_related("achievement_type", "scope")
        .order_by("-awarded_at", "-id")
    )

    context = {
        "season": season,
        "competition": comp,
        "seasons": seasons,
        "competitions": competitions,
        "player": player,
        "current_team": current_mem.team if current_mem else None,
        "team_history": history,
        "transfers": transfers,
        "achievements": achievements,
    }
    return render(request, "league/player_detail.html", context)


def fixtures_view(request):
    season, comp, seasons, competitions = _active_season_competition(request)

    scopes = []
    if season and comp:
        scopes = list(
            Scope.objects.filter(season=season, competition=comp)
            .select_related("division", "group")
            .order_by("division__order", "group__order")
        )

    data = []
    for sc in scopes:
        gws = list(
    Gameweek.objects.filter(fixtures__scope=sc)
    .distinct()
    .order_by("number", "id")
        ) 
        gw_blocks = []
        for gw in gws:
            fx = list(
                Fixture.objects.filter(scope=sc, gameweek=gw)
                .select_related("home_team", "away_team")
                .order_by("kickoff_at")
            )
            gw_blocks.append({"gw": gw, "fixtures": fx})
        data.append({"scope": sc, "gameweeks": gw_blocks})

    context = {
        "season": season,
        "competition": comp,
        "seasons": seasons,
        "competitions": competitions,
        "fixtures_by_scope": data,
    }
    return render(request, "league/fixtures.html", context)


def teams_list(request):
    teams = Team.objects.order_by("name")
    return render(request, "league/teams.html", {"teams": teams})


def team_detail(request, team_id: int):
    season, comp, seasons, competitions = _active_season_competition(request)
    team = get_object_or_404(Team, pk=team_id)

    # لاعبين الفريق الحاليين
    current_members = list(
        TeamMembership.objects.filter(season=season, team=team, end_date__isnull=True)
        .select_related("player")
        .order_by("player__name")
    )

    context = {
        "season": season,
        "competition": comp,
        "seasons": seasons,
        "competitions": competitions,
        "team": team,
        "current_members": current_members,
    }
    return render(request, "league/team_detail.html", context)


def compare_teams(request):
    season, comp, seasons, competitions = _active_season_competition(request)
    scope_id = request.GET.get("scope")
    team_a = request.GET.get("team_a")
    team_b = request.GET.get("team_b")

    scopes = []
    if season and comp:
        scopes = list(Scope.objects.filter(season=season, competition=comp).order_by("division__order", "group__order"))

    active_scope = Scope.objects.filter(id=scope_id).first() if scope_id else (scopes[0] if scopes else None)

    res = None
    if active_scope and team_a and team_b:
        res = head_to_head(active_scope, int(team_a), int(team_b))

    context = {
        "season": season,
        "competition": comp,
        "seasons": seasons,
        "competitions": competitions,
        "scopes": scopes,
        "active_scope": active_scope,
        "teams": Team.objects.order_by("name"),
        "team_a": int(team_a) if team_a else None,
        "team_b": int(team_b) if team_b else None,
        "result": res,
    }
    return render(request, "league/compare_teams.html", context)

def compare_players(request):
    season, comp, seasons, competitions = _active_season_competition(request)
    scope_id = request.GET.get("scope")
    player_a = request.GET.get("player_a")
    player_b = request.GET.get("player_b")

    scopes = []
    if season and comp:
        scopes = list(Scope.objects.filter(season=season, competition=comp).order_by("division__order", "group__order"))

    active_scope = Scope.objects.filter(id=scope_id).first() if scope_id else (scopes[0] if scopes else None)

    res = None
    if active_scope and player_a and player_b:
        res = player_vs_player(active_scope, int(player_a), int(player_b))

    # players list مع الصور
    players = Player.objects.order_by("name")

    # objects للاعبين المختارين (لإظهار الصور)
    a_obj = Player.objects.filter(id=player_a).first() if player_a else None
    b_obj = Player.objects.filter(id=player_b).first() if player_b else None

    return render(request, "league/compare_players.html", {
        "season": season,
        "competition": comp,
        "seasons": seasons,
        "competitions": competitions,
        "scopes": scopes,
        "active_scope": active_scope,
        "players": players,
        "player_a": int(player_a) if player_a else None,
        "player_b": int(player_b) if player_b else None,
        "a_obj": a_obj,
        "b_obj": b_obj,
        "result": res,
    })

from django.db.models import Q, Count, Sum, Max  

from django.db.models import Q

from django.db.models import Q
from collections import defaultdict

from collections import defaultdict

def awards(request):
    seasons = Season.objects.all().order_by("-start_date")
    competitions = Competition.objects.all().order_by("comp_type", "name")

    season_id = request.GET.get("season")
    comp_id = request.GET.get("competition")

    season = Season.objects.filter(id=season_id).first() or seasons.first()
    competition = (
        Competition.objects.filter(id=comp_id).first()
        or competitions.filter(comp_type=Competition.LEAGUE).first()
        or competitions.first()
    )

    ach_qs = (
        Achievement.objects.filter(season=season)
        .filter(Q(scope__competition=competition) | Q(scope__isnull=True))
        .select_related(
            "achievement_type",
            "player", "team",
            "scope", "scope__division", "scope__competition",
            "fixture",
            "opponent_team", "opponent_player",
        )
        .order_by("scope__division__order", "achievement_type__name", "-awarded_at", "-id")
    )

    # blocks: لكل Division قائمة جوائز grouped by type
    blocks = []

    # نجمع حسب division (ممكن None)
    by_division = defaultdict(list)
    for a in ach_qs:
        div = a.scope.division if a.scope_id else None
        by_division[div].append(a)

    # رتب الـ divisions: Premier/Second حسب order، وGeneral في الآخر
    divisions = [d for d in by_division.keys() if d is not None]
    divisions.sort(key=lambda d: (d.order, (d.name or "").lower()))

    ordered_divisions = divisions + ([None] if None in by_division else [])

    for div in ordered_divisions:
        items = by_division[div]
        grouped = defaultdict(list)
        for a in items:
            grouped[a.achievement_type].append(a)

        types_sorted = sorted(grouped.keys(), key=lambda t: (t.name or "").lower())

        blocks.append({
            "division": div,                 # None يعني General
            "types": types_sorted,
            "grouped": grouped,
        })

    return render(request, "league/awards.html", {
        "seasons": seasons,
        "competitions": competitions,
        "active_season": season,
        "active_competition": competition,
        "blocks": blocks,
    })



def award_type_detail(request, type_id: int):
    seasons = Season.objects.all()
    competitions = Competition.objects.all()

    season_id = request.GET.get("season")
    comp_id = request.GET.get("competition")

    season = Season.objects.filter(id=season_id).first() or seasons.first()
    competition = Competition.objects.filter(id=comp_id).first() or competitions.filter(comp_type=Competition.LEAGUE).first() or competitions.first()

    ach_type = get_object_or_404(AchievementType, pk=type_id)

    achievements = Achievement.objects.filter(
        season=season,
        achievement_type=ach_type,
    ).filter(
        Q(scope__competition=competition) | Q(scope__isnull=True)
    ).select_related("team", "player", "scope", "scope__competition").order_by("-awarded_at", "-id")

    return render(request, "league/award_type_detail.html", {
        "seasons": seasons,
        "competitions": competitions,
        "active_season": season,
        "active_competition": competition,
        "ach_type": ach_type,
        "achievements": achievements,
    })


def transfers_view(request):
    season, comp, seasons, competitions = _active_season_competition(request)

    transfers = (
        Transfer.objects.filter(season=season)
        .select_related("player", "from_team", "to_team", "season")
        .order_by("-date", "-id")
    )

    return render(request, "league/transfer.html", {
        "season": season,
        "competition": comp,
        "seasons": seasons,
        "competitions": competitions,
        "transfers": transfers,
    })

from .models import HallOfFameEntry

def hall_of_fame(request):
    season, comp, seasons, competitions = _active_season_competition(request)

    items = (
        HallOfFameEntry.objects
        .filter(season=season)
        .select_related("player", "team", "season")
        .order_by("-created_at", "-id")
    )

    return render(request, "league/hall_of_fame.html", {
        "season": season,
        "competition": comp,
        "seasons": seasons,
        "competitions": competitions,
        "items": items,
    })


def custom_404(request, exception):
    # template: league/404.html
    return render(request, "league/404.html", status=404)

def custom_500(request):
    # template: league/500.html
    return render(request, "league/500.html", status=500)
def players_overall(request):
    season, comp, seasons, competitions = _active_season_competition(request)

    # ترتيب شامل لكل اللاعبين داخل الموسم + البطولة (عبر كل الـ scopes)
    agg = (
        PlayerScore.objects
        .filter(result__fixture__is_played=True)
        .filter(result__fixture__scope__season=season, result__fixture__scope__competition=comp)
        .values("player_id")
        .annotate(
            total_points=Sum("points"),
            matches_played=Count("result__fixture_id", distinct=True),
        )
        .order_by("-total_points", "-matches_played")
    )

    pids = [r["player_id"] for r in agg]
    players = {p.id: p for p in Player.objects.filter(id__in=pids)}

    # الفريق الحالي في الموسم
    memberships = (
        TeamMembership.objects
        .filter(season=season, end_date__isnull=True, player_id__in=pids)
        .select_related("team")
    )
    current_team_by_player = {m.player_id: m.team for m in memberships}

    rows = []
    for r in agg:
        pid = r["player_id"]
        rows.append({
            "player": players.get(pid),
            "team": current_team_by_player.get(pid),
            "total_points": int(r["total_points"] or 0),
            "matches_played": int(r["matches_played"] or 0),
        })

    return render(request, "league/players_overall.html", {
        "season": season,
        "competition": comp,
        "seasons": seasons,
        "competitions": competitions,
        "rows": rows,
    })

