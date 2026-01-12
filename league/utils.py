from __future__ import annotations

from collections import defaultdict

from django.db.models import Q

from .models import Scope, Fixture


def head_to_head_points(scope: Scope, team_a_id: int, team_b_id: int) -> int:
    """
    يرجّع نقاط المواجهات المباشرة للفريق A ضد B:
    فوز=3 تعادل=1 خسارة=0 (حسب match_points داخل Fixture)
    """
    qs = Fixture.objects.filter(scope=scope, is_played=True).filter(
        (Q(home_team_id=team_a_id) & Q(away_team_id=team_b_id)) |
        (Q(home_team_id=team_b_id) & Q(away_team_id=team_a_id))
    ).only("home_team_id", "away_team_id", "home_match_points", "away_match_points")

    pts = 0
    for f in qs:
        if f.home_team_id == team_a_id:
            pts += int(f.home_match_points)
        else:
            pts += int(f.away_match_points)
    return pts


def sort_standings_with_h2h(scope: Scope, rows: list[dict]) -> list[dict]:
    """
    rows: list of dict فيها team_id, match_points, total_points, etc.
    ترتيب:
      1) match_points desc
      2) head-to-head (فقط داخل مجموعة التعادل)
      3) total_points desc
      4) name asc (fallback)
    """
    # group by match_points
    by_mp = defaultdict(list)
    for r in rows:
        by_mp[int(r["match_points"])].append(r)

    out = []
    for mp in sorted(by_mp.keys(), reverse=True):
        group = by_mp[mp]
        if len(group) <= 1:
            out += group
            continue

        team_ids = [g["team_id"] for g in group]
        h2h_sum = {tid: 0 for tid in team_ids}
        # مجموع نقاط المواجهات المباشرة ضد كل خصوم التعادل
        for i in range(len(team_ids)):
            for j in range(i + 1, len(team_ids)):
                a = team_ids[i]
                b = team_ids[j]
                a_pts = head_to_head_points(scope, a, b)
                b_pts = head_to_head_points(scope, b, a)
                h2h_sum[a] += a_pts
                h2h_sum[b] += b_pts

        group.sort(
            key=lambda r: (
                -int(r["match_points"]),
                -int(h2h_sum[r["team_id"]]),
                -int(r["total_points"]),
                (r.get("team_name") or "").lower(),
            )
        )
        out += group

    return out
