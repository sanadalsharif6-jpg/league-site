from __future__ import annotations

from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone


class Season(models.Model):
    name = models.CharField(max_length=20, unique=True)  # e.g. 2025/26
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        ordering = ["-start_date"]

    def __str__(self) -> str:
        return self.name


class Division(models.Model):
    name = models.CharField(max_length=50, unique=True)  # Premier / Second
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self) -> str:
        return self.name


class Group(models.Model):
    name = models.CharField(max_length=20, unique=True)  # Group A / Group B
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self) -> str:
        return self.name


class Competition(models.Model):
    LEAGUE = "LEAGUE"
    CUP = "CUP"
    SUPER_CUP = "SUPER_CUP"

    COMP_TYPES = [
        (LEAGUE, "League"),
        (CUP, "Cup"),
        (SUPER_CUP, "Super Cup"),
    ]

    name = models.CharField(max_length=60)
    comp_type = models.CharField(max_length=20, choices=COMP_TYPES)

    class Meta:
        unique_together = [("name", "comp_type")]
        ordering = ["comp_type", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_comp_type_display()})"


class Scope(models.Model):
    """
    The strict filter scope: Season + Competition + Division + Group
    """
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="scopes")
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="scopes")
    division = models.ForeignKey(Division, on_delete=models.CASCADE, related_name="scopes")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="scopes")

    class Meta:
        unique_together = [("season", "competition", "division", "group")]
        ordering = ["-season__start_date", "competition__comp_type", "division__order", "group__order"]

    def __str__(self) -> str:
        return f"{self.season} | {self.competition.name} | {self.division.name} | {self.group.name}"


class Team(models.Model):
    name = models.CharField(max_length=120, unique=True)
    logo = models.ImageField(upload_to="team_logos/", blank=True, null=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Player(models.Model):
    name = models.CharField(max_length=120, unique=True)
    photo = models.ImageField(upload_to="player_photos/", blank=True, null=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class TeamMembership(models.Model):
    """
    Enforce team members in a season (exactly 3 active members per team is enforced
    by admin/validation and also at result entry time).
    """
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="memberships")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="memberships")
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["season", "team"]),
            models.Index(fields=["season", "player"]),
        ]

    def __str__(self) -> str:
        return f"{self.season}: {self.player} -> {self.team}"

    def clean(self):
        if self.start_date < self.season.start_date or self.start_date > self.season.end_date:
            raise ValidationError("Membership start_date must be within the season.")
        if self.end_date and (self.end_date < self.season.start_date or self.end_date > self.season.end_date):
            raise ValidationError("Membership end_date must be within the season.")
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError("end_date cannot be before start_date.")

        # No overlapping memberships per player per season
        qs = TeamMembership.objects.filter(season=self.season, player=self.player).exclude(pk=self.pk)
        for other in qs:
            if _windows_overlap(self.start_date, self.end_date, other.start_date, other.end_date):
                raise ValidationError("Player has overlapping membership in this season.")

        # Basic enforcement: no more than 3 open memberships for a team in a season
        if self.end_date is None:
            active = TeamMembership.objects.filter(
                season=self.season, team=self.team, end_date__isnull=True
            ).exclude(pk=self.pk).count()
            if active >= 3:
                raise ValidationError("Team already has 3 active members for this season.")

    @property
    def is_active(self) -> bool:
        today = timezone.localdate()
        return self.start_date <= today and (self.end_date is None or self.end_date >= today)


def _windows_overlap(a_start, a_end, b_start, b_end) -> bool:
    a_end_eff = a_end or timezone.datetime.max.date()
    b_end_eff = b_end or timezone.datetime.max.date()
    return not (a_end_eff < b_start or b_end_eff < a_start)


class Transfer(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="transfers")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="transfers")
    from_team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="transfers_out")
    to_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="transfers_in")
    date = models.DateField()
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [
            models.Index(fields=["season", "date"]),
            models.Index(fields=["player", "date"]),
        ]

    def __str__(self) -> str:
        return f"{self.season}: {self.player} {self.from_team or '-'} -> {self.to_team} ({self.date})"





class Stage(models.Model):
    """A competition stage inside a Scope (e.g., Regular Season GW1-30, League Playoffs, Cup QF)."""

    REGULAR = "REGULAR"
    KNOCKOUT = "KNOCKOUT"
    STAGE_TYPES = [
        (REGULAR, "Regular Season"),
        (KNOCKOUT, "Knockout"),
    ]

    scope = models.ForeignKey(Scope, on_delete=models.CASCADE, related_name="stages")
    name = models.CharField(max_length=80)
    stage_type = models.CharField(max_length=20, choices=STAGE_TYPES)
    order = models.PositiveIntegerField(default=1)

    # For REGULAR stages (optional)
    start_gameweek = models.PositiveIntegerField(null=True, blank=True)
    end_gameweek = models.PositiveIntegerField(null=True, blank=True)

    # For KNOCKOUT stages: whether to render a bracket map (cup early rounds can be list-only)
    show_bracket = models.BooleanField(default=False)

    class Meta:
        unique_together = [("scope", "name")]
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.scope} | {self.name}"


class Bracket(models.Model):
    """Bracket container for a KNOCKOUT stage."""

    stage = models.OneToOneField(Stage, on_delete=models.CASCADE, related_name="bracket")
    title = models.CharField(max_length=120, blank=True, default="")
    teams_count = models.PositiveIntegerField(default=16)  # 4/8/16...
    two_legs = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.title or f"Bracket: {self.stage}"


class BracketRound(models.Model):
    bracket = models.ForeignKey(Bracket, on_delete=models.CASCADE, related_name="rounds")
    name = models.CharField(max_length=60)  # Round of 16, Quarterfinals, Semis, Final
    order = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = [("bracket", "order")]
        ordering = ["bracket", "order"]

    def __str__(self) -> str:
        return f"{self.bracket.stage} | {self.name}"


class BracketTie(models.Model):
    """One tie in a knockout round. Supports 1 or 2 legs by linking to 1-2 Fixtures."""

    round = models.ForeignKey(BracketRound, on_delete=models.CASCADE, related_name="ties")
    tie_no = models.PositiveIntegerField(default=1)

    leg1_fixture = models.OneToOneField(
        "Fixture",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bracket_leg1_of",
        help_text="First leg fixture (required for two-legs; optional while drafting).",
    )
    leg2_fixture = models.OneToOneField(
        "Fixture",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bracket_leg2_of",
        help_text="Second leg fixture (only for two-legs).",
    )

    # Optional seeding
    home_seed = models.PositiveIntegerField(null=True, blank=True)
    away_seed = models.PositiveIntegerField(null=True, blank=True)

    # Optional links to previous ties (used to describe 'Winner of Tie X')
    home_winner_from = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="home_to"
    )
    away_winner_from = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="away_to"
    )

    # Winner (set by admin or computed later)
    winner_team = models.ForeignKey(
        Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="won_ties"
    )

    class Meta:
        unique_together = [("round", "tie_no")]
        ordering = ["round__order", "tie_no"]

    def __str__(self) -> str:
        return f"{self.round} | Tie {self.tie_no}"
class Gameweek(models.Model):
    number = models.PositiveIntegerField()
    name = models.CharField(max_length=60, blank=True, default="")

    class Meta:
        ordering = ["number", "id"]

    def __str__(self) -> str:
        return self.name or f"GW{self.number}"


class Fixture(models.Model):
    scope = models.ForeignKey(Scope, on_delete=models.CASCADE, related_name="fixtures")
    gameweek = models.ForeignKey(Gameweek, on_delete=models.CASCADE, related_name="fixtures")
    kickoff_at = models.DateTimeField()

    stage = models.ForeignKey(
        Stage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fixtures",
        help_text="Optional stage (e.g., Regular Season, League Playoffs, Cup Quarterfinals).",
    )


    home_team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="home_fixtures")
    away_team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="away_fixtures")

    # NEW: Replay support (for CUP/SUPER_CUP draws)
    replay_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replays",
        help_text="If this is a replay match, link it to the original fixture.",
    )

    # Calculated strictly from Result + PlayerScore
    home_total_points = models.IntegerField(default=0)
    away_total_points = models.IntegerField(default=0)
    home_match_points = models.IntegerField(default=0)  # 3/1/0 (used for LEAGUE standings only)
    away_match_points = models.IntegerField(default=0)  # 3/1/0 (used for LEAGUE standings only)
    is_played = models.BooleanField(default=False)

    class Meta:
        ordering = ["kickoff_at", "id"]
        indexes = [
            models.Index(fields=["scope", "gameweek"]),
            models.Index(fields=["scope", "kickoff_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.scope} | {self.home_team} vs {self.away_team} | {self.kickoff_at:%Y-%m-%d %H:%M}"

    def clean(self):
        if self.home_team_id == self.away_team_id:
            raise ValidationError("Home and away team must be different.")

        # replay must match original fixture teams/scope
        if self.replay_of_id:
            if self.replay_of_id == self.id:
                raise ValidationError("Fixture cannot be replay of itself.")
            orig = Fixture.objects.filter(pk=self.replay_of_id).select_related("scope").first()
            if orig:
                if orig.scope_id != self.scope_id:
                    raise ValidationError("Replay fixture must belong to the same scope as original.")
                if orig.home_team_id != self.home_team_id or orig.away_team_id != self.away_team_id:
                    raise ValidationError("Replay fixture must have same home/away teams as original.")


class Result(models.Model):
    fixture = models.OneToOneField(Fixture, on_delete=models.CASCADE, related_name="result")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]

    def __str__(self) -> str:
        return f"Result: {self.fixture}"


class PlayerScore(models.Model):
    HOME = "HOME"
    AWAY = "AWAY"
    SIDE_CHOICES = [(HOME, "Home"), (AWAY, "Away")]

    result = models.ForeignKey(Result, on_delete=models.CASCADE, related_name="player_scores")
    side = models.CharField(max_length=4, choices=SIDE_CHOICES)
    player = models.ForeignKey(Player, on_delete=models.PROTECT, related_name="scores")
    points = models.IntegerField(default=0)

    class Meta:
        unique_together = [("result", "side", "player")]
        indexes = [
            models.Index(fields=["result", "side"]),
            models.Index(fields=["player"]),
        ]

    def __str__(self) -> str:
        return f"{self.result.fixture} | {self.side} | {self.player} = {self.points}"


class AchievementType(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True, default="")
    icon_key = models.CharField(max_length=60, blank=True, default="")
    is_team = models.BooleanField(default=False)
    is_player = models.BooleanField(default=False)

    def clean(self):
        if not self.is_team and not self.is_player:
            raise ValidationError("AchievementType must apply to team and/or player.")

    def __str__(self) -> str:
        return self.name

class Achievement(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="achievements")
    scope = models.ForeignKey(Scope, on_delete=models.SET_NULL, null=True, blank=True, related_name="achievements")
    achievement_type = models.ForeignKey(AchievementType, on_delete=models.PROTECT, related_name="achievements")

    # Owner (exactly one)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, null=True, blank=True, related_name="achievements")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, null=True, blank=True, related_name="achievements")

    # When
    awarded_at = models.DateTimeField(default=timezone.now)

    # Context (optional)
    fixture = models.ForeignKey(
        Fixture,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="achievements",
        help_text="Optional: link this award to a specific fixture (match).",
    )

    # "Against whom" (optional)
    opponent_team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="achievements_against_team",
        help_text="Optional: opponent team for this award.",
    )
    opponent_player = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="achievements_against_player",
        help_text="Optional: opponent player for this award.",
    )

    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-awarded_at", "-id"]
        indexes = [
            models.Index(fields=["season", "awarded_at"]),
            models.Index(fields=["achievement_type", "awarded_at"]),
        ]

    def __str__(self) -> str:
        owner = self.player or self.team
        return f"{self.achievement_type} - {owner} ({self.season})"

    def clean(self):
        # 1) Must belong to exactly one: team OR player
        if (self.team is None) == (self.player is None):
            raise ValidationError("Achievement must belong to exactly one: team OR player.")

        # 2) Respect type applicability
        if self.team and not self.achievement_type.is_team:
            raise ValidationError("This achievement type is not allowed for teams.")
        if self.player and not self.achievement_type.is_player:
            raise ValidationError("This achievement type is not allowed for players.")

        # 3) Scope season must match achievement season
        if self.scope and self.scope.season_id != self.season_id:
            raise ValidationError("Achievement scope season must match achievement season.")

        # 4) If player award: team is REQUIRED (باش نقدر نطلع شعار الفريق واسم الفريق دايمًا)
        if self.player and self.team is None:
            raise ValidationError("Player achievements must have a team selected.")

        # 5) Fixture validation (if provided)
        if self.fixture:
            # fixture scope season must match achievement season
            if self.fixture.scope.season_id != self.season_id:
                raise ValidationError("Achievement fixture must be within the same season.")

            # if achievement has scope, fixture must be within same scope
            if self.scope and self.fixture.scope_id != self.scope_id:
                raise ValidationError("Achievement fixture must belong to the same scope as the achievement scope.")

            # if player/team selected, the team must be one of fixture teams
            if self.team_id and self.team_id not in (self.fixture.home_team_id, self.fixture.away_team_id):
                raise ValidationError("Selected team must be either the home or away team of the fixture.")

        # 6) Opponent rules:
        # - opponent_player alone is allowed
        # - opponent_team alone is allowed
        # - both allowed
        # - but if fixture exists and opponent_team is set, it must be the other team
        if self.fixture and self.opponent_team_id:
            if self.team_id and self.opponent_team_id == self.team_id:
                raise ValidationError("Opponent team cannot be the same as the award team.")
            if self.opponent_team_id not in (self.fixture.home_team_id, self.fixture.away_team_id):
                raise ValidationError("Opponent team must be one of the fixture teams.")

            # ensure it's the other side (if team is set)
            if self.team_id:
                # award team is home -> opponent must be away, etc.
                if self.team_id == self.fixture.home_team_id and self.opponent_team_id != self.fixture.away_team_id:
                    raise ValidationError("Opponent team must be the other team in the fixture.")
                if self.team_id == self.fixture.away_team_id and self.opponent_team_id != self.fixture.home_team_id:
                    raise ValidationError("Opponent team must be the other team in the fixture.")

        # 7) Prevent nonsense: opponent_player cannot be the same as award player
        if self.player_id and self.opponent_player_id and self.player_id == self.opponent_player_id:
            raise ValidationError("Opponent player cannot be the same as the award player.")

class TeamStanding(models.Model):
    scope = models.ForeignKey(Scope, on_delete=models.CASCADE, related_name="team_standings")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="team_standings")

    played = models.PositiveIntegerField(default=0)
    wins = models.PositiveIntegerField(default=0)
    draws = models.PositiveIntegerField(default=0)
    losses = models.PositiveIntegerField(default=0)

    match_points = models.IntegerField(default=0)
    total_points = models.IntegerField(default=0)
    form_last5 = models.CharField(max_length=20, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("scope", "team")]
        indexes = [
            models.Index(fields=["scope", "match_points"]),
            models.Index(fields=["scope", "total_points"]),
        ]

    def __str__(self) -> str:
        return f"{self.scope} - {self.team}"


class PlayerStanding(models.Model):
    scope = models.ForeignKey(Scope, on_delete=models.CASCADE, related_name="player_standings")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="player_standings")

    matches_played = models.PositiveIntegerField(default=0)
    total_points = models.IntegerField(default=0)
    best_match_points = models.IntegerField(default=0)
    average_points = models.FloatField(default=0.0)
    stddev_points = models.FloatField(default=0.0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("scope", "player")]
        indexes = [models.Index(fields=["scope", "total_points"])]

    def __str__(self) -> str:
        return f"{self.scope} - {self.player}"


class RecordSnapshot(models.Model):
    scope = models.OneToOneField(Scope, on_delete=models.CASCADE, related_name="records")

    biggest_win_margin = models.IntegerField(default=0)
    biggest_win_fixture = models.ForeignKey(Fixture, on_delete=models.SET_NULL, null=True, blank=True, related_name="record_biggest_win")

    highest_team_match_score = models.IntegerField(default=0)
    highest_team_match_fixture = models.ForeignKey(Fixture, on_delete=models.SET_NULL, null=True, blank=True, related_name="record_highest_team_score")
    highest_team_match_team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="record_highest_team")

    highest_player_score = models.IntegerField(default=0)
    highest_player_score_fixture = models.ForeignKey(Fixture, on_delete=models.SET_NULL, null=True, blank=True, related_name="record_highest_player_fixture")
    highest_player = models.ForeignKey(Player, on_delete=models.SET_NULL, null=True, blank=True, related_name="record_highest_player")

    longest_win_streak = models.IntegerField(default=0)
    longest_unbeaten_streak = models.IntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Records: {self.scope}"


class PowerRanking(models.Model):
    scope = models.ForeignKey(Scope, on_delete=models.CASCADE, related_name="power_rankings")
    gameweek = models.ForeignKey(Gameweek, on_delete=models.CASCADE, related_name="power_rankings")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="power_rankings")

    rank = models.PositiveIntegerField()
    score = models.FloatField(default=0.0)

    class Meta:
        unique_together = [("scope", "gameweek", "team")]
        ordering = ["scope", "gameweek__number", "rank"]

    def __str__(self) -> str:
        return f"{self.scope} GW{self.gameweek.number} #{self.rank} {self.team}"

class HallOfFameEntry(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="hof_entries")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="hof_entries")
    note = models.TextField(blank=True, default="")
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="hof_entries")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        unique_together = [("season", "player")]

    def __str__(self) -> str:
        return f"HOF: {self.player} ({self.season})"
