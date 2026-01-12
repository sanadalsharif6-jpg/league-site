from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum, Count, Q, Max
from django.utils import timezone

from .models import (
    Season, Scope, Team, Player,
    TeamMembership, Transfer,
    Fixture, Result, PlayerScore,
    TeamStanding, PlayerStanding,
    RecordSnapshot, PowerRanking, Gameweek,
    Competition,
)


@dataclass(frozen=True)
class TeamRow:
    team_id: int
    played: int
    wins: int
    draws: int
    losses: int
    match_points: int
    total_points: int
    form_last5: str


def members_of_team_on_date(season: Season, team_id: int, on_date) -> list[int]:
    qs = TeamMembership.objects.filter(
        season=season,
        team_id=team_id,
        start_date__lte=on_date,
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=on_date))
    return list(qs.values_list("player_id", flat=True))


@transaction.atomic
def apply_transfer_memberships(transfer_id: int) -> None:
    tr = Transfer.objects.select_related("season", "player", "from_team", "to_team").get(pk=transfer_id)

    active = TeamMembership.objects.filter(season=tr.season, player=tr.player, end_date__isnull=True).first()
    if active:
        if tr.date <= active.start_date:
            active.end_date = active.start_date
        else:
            active.end_date = tr.date - timedelta(days=1)
        active.full_clean()
        active.save()

    mem = TeamMembership(
        season=tr.season,
        team=tr.to_team,
        player=tr.player,
        start_date=tr.date,
        end_date=None,
    )
    mem.full_clean()
    mem.save()


def cup_winner_team_id(original_fixture: Fixture) -> int | None:
    """
    CUP/SUPER_CUP: If draw => replay needed.
    Winner is determined from the latest played match among:
    - the original fixture
    - any fixtures with replay_of = original_fixture
    """
    chain = Fixture.objects.filter(
        Q(id=original_fixture.id) | Q(replay_of=original_fixture)
    ).order_by("kickoff_at", "id")

    played = [f for f in chain if f.is_played]
    if not played:
        return None

    last = played[-1]
    if last.home_total_points > last.away_total_points:
        return last.home_team_id
    if last.home_total_points < last.away_total_points:
        return last.away_team_id
    return None  # draw => replay needed


@transaction.atomic
def recalculate_fixture_totals(fixture_id: int) -> None:
    fixture = Fixture.objects.select_related("scope__season", "scope__competition").get(pk=fixture_id)

    if not hasattr(fixture, "result"):
        fixture.home_total_points = 0
        fixture.away_total_points = 0
        fixture.home_match_points = 0
        fixture.away_match_points = 0
        fixture.is_played = False
        fixture.save(update_fields=[
            "home_total_points", "away_total_points",
            "home_match_points", "away_match_points",
            "is_played"
        ])
        return

    res = fixture.result
    scores = list(PlayerScore.objects.filter(result=res).select_related("player"))

    home_scores = [s for s in scores if s.side == PlayerScore.HOME]
    away_scores = [s for s in scores if s.side == PlayerScore.AWAY]

    # أثناء الإدخال/قبل اكتمال البيانات: لا نطيح النظام
    if len(scores) != 6 or len(home_scores) != 3 or len(away_scores) != 3:
        fixture.home_total_points = 0
        fixture.away_total_points = 0
        fixture.home_match_points = 0
        fixture.away_match_points = 0
        fixture.is_played = False
        fixture.save(update_fields=[
            "home_total_points", "away_total_points",
            "home_match_points", "away_match_points",
            "is_played"
        ])
        return

    on_date = timezone.localtime(fixture.kickoff_at).date()
    season = fixture.scope.season

    home_member_ids = set(members_of_team_on_date(season, fixture.home_team_id, on_date))
    away_member_ids = set(members_of_team_on_date(season, fixture.away_team_id, on_date))

    for s in home_scores:
        if s.player_id not in home_member_ids:
            raise ValueError(f"HOME player {s.player} is not in {fixture.home_team} on kickoff date.")
    for s in away_scores:
        if s.player_id not in away_member_ids:
            raise ValueError(f"AWAY player {s.player} is not in {fixture.away_team} on kickoff date.")

    home_total = sum(int(s.points) for s in home_scores)
    away_total = sum(int(s.points) for s in away_scores)

    # League points (standings) only meaningful for LEAGUE
    if home_total > away_total:
        hmp, amp = 3, 0
    elif home_total < away_total:
        hmp, amp = 0, 3
    else:
        hmp, amp = 1, 1

    fixture.home_total_points = home_total
    fixture.away_total_points = away_total
    fixture.home_match_points = int(hmp)
    fixture.away_match_points = int(amp)
    fixture.is_played = True
    fixture.save(update_fields=[
        "home_total_points", "away_total_points",
        "home_match_points", "away_match_points",
        "is_played"
    ])


def _team_form_last5(scope: Scope, team_id: int) -> str:
    fixtures = (
        Fixture.objects.filter(scope=scope, is_played=True)
        .filter(Q(home_team_id=team_id) | Q(away_team_id=team_id))
        .order_by("-kickoff_at")
        .only("home_team_id", "away_team_id", "home_match_points", "away_match_points")[:5]
    )
    out = []
    for f in fixtures:
        mp = f.home_match_points if f.home_team_id == team_id else f.away_match_points
        out.append("W" if mp == 3 else "D" if mp == 1 else "L")
    return ",".join(out)


def compute_team_rows(scope: Scope) -> list[TeamRow]:
    fixtures = Fixture.objects.filter(scope=scope, is_played=True).only(
        "home_team_id", "away_team_id", "home_total_points", "away_total_points",
        "home_match_points", "away_match_points", "kickoff_at"
    )

    team_ids = set(fixtures.values_list("home_team_id", flat=True)) | set(fixtures.values_list("away_team_id", flat=True))
    stats = {tid: {"played": 0, "wins": 0, "draws": 0, "losses": 0, "mp": 0, "tp": 0} for tid in team_ids}

    for f in fixtures:
        h = stats[f.home_team_id]
        a = stats[f.away_team_id]

        h["played"] += 1
        a["played"] += 1

        h["tp"] += int(f.home_total_points)
        a["tp"] += int(f.away_total_points)

        h["mp"] += int(f.home_match_points)
        a["mp"] += int(f.away_match_points)

        if f.home_match_points == 3:
            h["wins"] += 1
            a["losses"] += 1
        elif f.home_match_points == 0:
            h["losses"] += 1
            a["wins"] += 1
        else:
            h["draws"] += 1
            a["draws"] += 1

    rows = []
    for tid, s in stats.items():
        rows.append(
            TeamRow(
                team_id=tid,
                played=s["played"],
                wins=s["wins"],
                draws=s["draws"],
                losses=s["losses"],
                match_points=s["mp"],
                total_points=s["tp"],
                form_last5=_team_form_last5(scope, tid),
            )
        )

    names = {t.id: t.name for t in Team.objects.filter(id__in=list(team_ids))}
    rows.sort(key=lambda r: (-r.match_points, -r.total_points, (names.get(r.team_id) or "").lower()))
    return rows


def compute_player_rows(scope: Scope):
    qs = (
        PlayerScore.objects.filter(result__fixture__scope=scope, result__fixture__is_played=True)
        .values("player_id", "result__fixture_id")
        .annotate(points=Sum("points"), k=Max("result__fixture__kickoff_at"))
    )

    per_player = {}
    for row in qs:
        pid = row["player_id"]
        pts = int(row["points"] or 0)
        per_player.setdefault(pid, []).append(pts)

    rows = []
    for pid, pts_list in per_player.items():
        n = len(pts_list)
        total = sum(pts_list)
        best = max(pts_list) if pts_list else 0
        avg = (total / n) if n else 0.0
        if n >= 2:
            mean = avg
            var = sum((x - mean) ** 2 for x in pts_list) / (n - 1)
            sd = sqrt(var)
        else:
            sd = 0.0
        rows.append((pid, n, total, best, float(avg), float(sd)))

    names = {p.id: p.name for p in Player.objects.filter(id__in=list(per_player.keys()))}
    rows.sort(key=lambda r: (-r[2], -r[4], (names.get(r[0]) or "").lower()))
    return rows


@transaction.atomic
def rebuild_scope_materialized(scope_id: int) -> None:
    scope = Scope.objects.select_related("season", "competition", "division", "group").get(pk=scope_id)

    # 1) ensure fixture totals consistent
    fixture_ids = list(Fixture.objects.filter(scope=scope).values_list("id", flat=True))
    for fid in fixture_ids:
        f = Fixture.objects.only("id").get(pk=fid)
        if hasattr(f, "result") or Fixture.objects.filter(pk=fid, is_played=True).exists():
            recalculate_fixture_totals(fid)

    # 2) LEAGUE only: build standings / player standings / records / power rankings
    if scope.competition.comp_type != Competition.LEAGUE:
        # for CUP/SUPER_CUP: standings are not meaningful
        TeamStanding.objects.filter(scope=scope).delete()
        PlayerStanding.objects.filter(scope=scope).delete()
        PowerRanking.objects.filter(scope=scope).delete()
        # Records optional: keep or reset. Here we keep as-is (no rebuild).
        return

    # Team standings
    TeamStanding.objects.filter(scope=scope).delete()
    team_rows = compute_team_rows(scope)
    TeamStanding.objects.bulk_create(
        [
            TeamStanding(
                scope=scope,
                team_id=r.team_id,
                played=r.played,
                wins=r.wins,
                draws=r.draws,
                losses=r.losses,
                match_points=r.match_points,
                total_points=r.total_points,
                form_last5=r.form_last5,
            )
            for r in team_rows
        ],
        batch_size=500,
    )

    # Player standings
    PlayerStanding.objects.filter(scope=scope).delete()
    player_rows = compute_player_rows(scope)
    PlayerStanding.objects.bulk_create(
        [
            PlayerStanding(
                scope=scope,
                player_id=pid,
                matches_played=n,
                total_points=total,
                best_match_points=best,
                average_points=avg,
                stddev_points=sd,
            )
            for (pid, n, total, best, avg, sd) in player_rows
        ],
        batch_size=500,
    )

    # Records
    rebuild_records(scope)

    # Power rankings
    rebuild_power_rankings(scope)


@transaction.atomic
def rebuild_records(scope: Scope) -> None:
    fixtures = Fixture.objects.filter(scope=scope, is_played=True).order_by("kickoff_at").select_related("home_team", "away_team")
    rec, _ = RecordSnapshot.objects.get_or_create(scope=scope)

    biggest_margin = 0
    biggest_fixture = None

    highest_team_score = 0
    highest_team_fixture = None
    highest_team = None

    highest_player_score = 0
    highest_player = None
    highest_player_fixture = None

    win_streak_best = 0
    unbeaten_streak_best = 0
    win_streak = {}
    unbeaten_streak = {}

    for f in fixtures:
        margin = abs(int(f.home_total_points) - int(f.away_total_points))
        if margin > biggest_margin:
            biggest_margin = margin
            biggest_fixture = f

        if int(f.home_total_points) > highest_team_score:
            highest_team_score = int(f.home_total_points)
            highest_team_fixture = f
            highest_team = f.home_team
        if int(f.away_total_points) > highest_team_score:
            highest_team_score = int(f.away_total_points)
            highest_team_fixture = f
            highest_team = f.away_team

        if hasattr(f, "result"):
            ps = (
                PlayerScore.objects.filter(result__fixture=f)
                .values("player_id")
                .annotate(p=Sum("points"))
                .order_by("-p")
                .first()
            )
            if ps and int(ps["p"] or 0) > highest_player_score:
                highest_player_score = int(ps["p"] or 0)
                highest_player = Player.objects.get(pk=ps["player_id"])
                highest_player_fixture = f

        def update(team_id: int, mp: int):
            win_streak.setdefault(team_id, 0)
            unbeaten_streak.setdefault(team_id, 0)
            nonlocal win_streak_best, unbeaten_streak_best

            if mp == 3:
                win_streak[team_id] += 1
                unbeaten_streak[team_id] += 1
            elif mp == 1:
                win_streak[team_id] = 0
                unbeaten_streak[team_id] += 1
            else:
                win_streak[team_id] = 0
                unbeaten_streak[team_id] = 0

            win_streak_best = max(win_streak_best, win_streak[team_id])
            unbeaten_streak_best = max(unbeaten_streak_best, unbeaten_streak[team_id])

        update(f.home_team_id, int(f.home_match_points))
        update(f.away_team_id, int(f.away_match_points))

    rec.biggest_win_margin = biggest_margin
    rec.biggest_win_fixture = biggest_fixture
    rec.highest_team_match_score = highest_team_score
    rec.highest_team_match_fixture = highest_team_fixture
    rec.highest_team_match_team = highest_team
    rec.highest_player_score = highest_player_score
    rec.highest_player = highest_player
    rec.highest_player_score_fixture = highest_player_fixture
    rec.longest_win_streak = win_streak_best
    rec.longest_unbeaten_streak = unbeaten_streak_best
    rec.save()


@transaction.atomic
def rebuild_power_rankings(scope: Scope) -> None:
    PowerRanking.objects.filter(scope=scope).delete()

    team_standings = list(TeamStanding.objects.filter(scope=scope).select_related("team"))
    if not team_standings:
        return

    gameweeks = list(
    Gameweek.objects.filter(fixtures__scope=scope)
    .distinct()
    .order_by("number", "id")
)
    if not gameweeks:
        return

    team_ids = [ts.team_id for ts in team_standings]

    for gw in gameweeks:
        fixtures = Fixture.objects.filter(scope=scope, is_played=True, gameweek__number__lte=gw.number).only(
            "home_team_id", "away_team_id", "home_total_points", "away_total_points"
        )

        totals = {tid: 0 for tid in team_ids}
        for f in fixtures:
            totals[f.home_team_id] += int(f.home_total_points)
            totals[f.away_team_id] += int(f.away_total_points)

        max_total = max(totals.values()) if totals else 1
        max_total = max_total or 1

        form_scores = {}
        for tid in team_ids:
            form = _team_form_last5(scope, tid)
            s = 0.0
            if form:
                for x in form.split(","):
                    s += 1.0 if x == "W" else 0.5 if x == "D" else 0.0
                s = s / 5.0
            form_scores[tid] = s

        scored = []
        for tid in team_ids:
            norm_total = totals[tid] / float(max_total)
            score = 0.65 * norm_total + 0.35 * form_scores[tid]
            scored.append((tid, float(score)))

        names = {t.id: t.name for t in Team.objects.filter(id__in=team_ids)}
        scored.sort(key=lambda x: (-x[1], (names.get(x[0]) or "").lower()))

        bulk = []
        for idx, (tid, score) in enumerate(scored, start=1):
            bulk.append(PowerRanking(scope=scope, gameweek=gw, team_id=tid, rank=idx, score=score))
        PowerRanking.objects.bulk_create(bulk, batch_size=500)


def head_to_head(scope: Scope, team_a_id: int, team_b_id: int):
    qs = Fixture.objects.filter(scope=scope, is_played=True).filter(
        (Q(home_team_id=team_a_id) & Q(away_team_id=team_b_id)) |
        (Q(home_team_id=team_b_id) & Q(away_team_id=team_a_id))
    ).order_by("kickoff_at")

    played = qs.count()
    a_w = a_d = a_l = 0
    a_pts = b_pts = 0
    biggest_margin = 0
    biggest_fixture = None

    for f in qs:
        if f.home_team_id == team_a_id:
            a_pts += int(f.home_total_points); b_pts += int(f.away_total_points)
            mp = int(f.home_match_points)
        else:
            a_pts += int(f.away_total_points); b_pts += int(f.home_total_points)
            mp = int(f.away_match_points)

        if mp == 3: a_w += 1
        elif mp == 1: a_d += 1
        else: a_l += 1

        margin = abs(int(f.home_total_points) - int(f.away_total_points))
        if margin > biggest_margin:
            biggest_margin = margin
            biggest_fixture = f

    return {
        "played": played,
        "a_w": a_w, "a_d": a_d, "a_l": a_l,
        "a_points": a_pts, "b_points": b_pts,
        "a_avg": (a_pts / played) if played else 0.0,
        "b_avg": (b_pts / played) if played else 0.0,
        "biggest_margin": biggest_margin,
        "biggest_fixture": biggest_fixture,
    }


def player_vs_player(scope: Scope, player_a_id: int, player_b_id: int):
    a = PlayerStanding.objects.filter(scope=scope, player_id=player_a_id).select_related("player").first()
    b = PlayerStanding.objects.filter(scope=scope, player_id=player_b_id).select_related("player").first()

    both_fixtures = (
        PlayerScore.objects.filter(
            result__fixture__scope=scope,
            result__fixture__is_played=True,
            player_id__in=[player_a_id, player_b_id]
        )
        .values("result__fixture_id")
        .annotate(c=Count("player_id", distinct=True))
        .filter(c=2)
        .values_list("result__fixture_id", flat=True)
    )
    both_fixtures = list(both_fixtures)

    head_to_head_rows = []
    for fid in both_fixtures[:50]:
        f = Fixture.objects.get(pk=fid)
        a_pts = PlayerScore.objects.filter(result__fixture_id=fid, player_id=player_a_id).aggregate(s=Sum("points"))["s"] or 0
        b_pts = PlayerScore.objects.filter(result__fixture_id=fid, player_id=player_b_id).aggregate(s=Sum("points"))["s"] or 0
        head_to_head_rows.append({"fixture": f, "a_pts": int(a_pts), "b_pts": int(b_pts)})

    def last5(player_id: int):
        rows = (
            PlayerScore.objects.filter(result__fixture__scope=scope, result__fixture__is_played=True, player_id=player_id)
            .values("result__fixture_id")
            .annotate(p=Sum("points"), k=Max("result__fixture__kickoff_at"))
            .order_by("-k")[:5]
        )
        return [int(r["p"] or 0) for r in rows]

    return {
        "a": a,
        "b": b,
        "head_to_head": head_to_head_rows,
        "a_last5": last5(player_a_id),
        "b_last5": last5(player_b_id),
    }
