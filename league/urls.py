from django.urls import path

from . import views

app_name = "league"

urlpatterns = [
    path("", views.home, name="home"),
    path("standings/", views.standings, name="standings"),
    path("fixtures/", views.fixtures_view, name="fixtures"),
    path("playoffs/", views.playoffs_index, name="playoffs"),
    path("playoffs/stage/<int:stage_id>/", views.stage_detail, name="stage_detail"),
    path("teams/", views.teams_list, name="teams"),
    path("teams/<int:team_id>/", views.team_detail, name="team_detail"),
    path("players/", views.players_list, name="players"),
    path("players/<int:player_id>/", views.player_detail, name="player_detail"),
    path("compare/teams/", views.compare_teams, name="compare_teams"),
    path("compare/players/", views.compare_players, name="compare_players"),
    path("awards/", views.awards, name="awards"),
    path("awards/<int:type_id>/", views.award_type_detail, name="award_type_detail"),
    path("transfers/", views.transfers_view, name="transfers"),
    path("hall-of-fame/", views.hall_of_fame, name="hall_of_fame"),
    path("players/overall/", views.players_overall, name="players_overall"),

]
