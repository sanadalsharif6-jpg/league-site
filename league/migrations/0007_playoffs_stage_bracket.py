from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("league", "0006_alter_gameweek_options_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Stage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80)),
                ("stage_type", models.CharField(choices=[("REGULAR", "Regular Season"), ("KNOCKOUT", "Knockout")], max_length=20)),
                ("order", models.PositiveIntegerField(default=1)),
                ("start_gameweek", models.PositiveIntegerField(blank=True, null=True)),
                ("end_gameweek", models.PositiveIntegerField(blank=True, null=True)),
                ("show_bracket", models.BooleanField(default=False)),
                ("scope", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="stages", to="league.scope")),
            ],
            options={
                "ordering": ["order", "id"],
                "unique_together": {("scope", "name")},
            },
        ),
        migrations.AddField(
            model_name="fixture",
            name="stage",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional stage (e.g., Regular Season, League Playoffs, Cup Quarterfinals).",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="fixtures",
                to="league.stage",
            ),
        ),
        migrations.CreateModel(
            name="Bracket",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(blank=True, default="", max_length=120)),
                ("teams_count", models.PositiveIntegerField(default=16)),
                ("two_legs", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("stage", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="bracket", to="league.stage")),
            ],
        ),
        migrations.CreateModel(
            name="BracketRound",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=60)),
                ("order", models.PositiveIntegerField(default=1)),
                ("bracket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rounds", to="league.bracket")),
            ],
            options={
                "ordering": ["bracket", "order"],
                "unique_together": {("bracket", "order")},
            },
        ),
        migrations.CreateModel(
            name="BracketTie",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tie_no", models.PositiveIntegerField(default=1)),
                ("home_seed", models.PositiveIntegerField(blank=True, null=True)),
                ("away_seed", models.PositiveIntegerField(blank=True, null=True)),
                ("away_winner_from", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="away_to", to="league.brackettie")),
                ("home_winner_from", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="home_to", to="league.brackettie")),
                ("leg1_fixture", models.OneToOneField(blank=True, help_text="First leg fixture (required for two-legs; optional while drafting).", null=True, on_delete=django.db.models.deletion.PROTECT, related_name="bracket_leg1_of", to="league.fixture")),
                ("leg2_fixture", models.OneToOneField(blank=True, help_text="Second leg fixture (only for two-legs).", null=True, on_delete=django.db.models.deletion.PROTECT, related_name="bracket_leg2_of", to="league.fixture")),
                ("round", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ties", to="league.bracketround")),
                ("winner_team", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="won_ties", to="league.team")),
            ],
            options={
                "ordering": ["round__order", "tie_no"],
                "unique_together": {("round", "tie_no")},
            },
        ),
    ]
