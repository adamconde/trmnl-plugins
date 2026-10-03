"""Tests for src/transform.py against recorded MLB Stats API responses.

Fixtures are MLB feed responses (relay/mlb_relay.py MLB_URL) for a finished postseason (2025),
one captured mid-Wild Card round with a game in progress (2026), and one the day before the
Division Series with probable starters and venues (2026_ds).

Run from the plugin directory: python3 -m unittest discover tests
"""

import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "src"))

import transform  # noqa: E402

TRMNL = {"user": {"time_zone_iana": "America/New_York", "utc_offset": -14400}}


def load(season):
    """Return the recorded feed for ``season`` merged with a trmnl namespace."""
    data = json.loads((HERE / "fixtures" / f"postseason_{season}.json").read_text())
    data["trmnl"] = copy.deepcopy(TRMNL)
    return data


def with_starters_and_venues(data, pitcher="Gerrit Cole", venue="Tropicana Field"):
    """Add a probable starter to every team and a venue to every game (fixtures predate both)."""
    for entry in data["series"]:
        for game in entry["games"]:
            game["venue"] = {"id": 12, "name": venue}
            for side in game["teams"].values():
                side["probablePitcher"] = {"id": 1, "fullName": pitcher}
    return data


def find(result, series_id):
    """Return the series model with ``series_id`` from anywhere in the bracket."""
    bracket = result["bracket"]
    everything = [bracket.get("ws")] + [s for lg in ("al", "nl") for rnd in bracket[lg].values() for s in rnd]
    return next(s for s in everything if s and s["id"] == series_id)


class CompletedPostseason(unittest.TestCase):
    """2025: every series finished."""

    def setUp(self):
        self.result = transform.run(load(2025))

    def test_series_records_and_winners(self):
        ws = find(self.result, "W_1")
        self.assertEqual(ws["state"], "final")
        self.assertEqual([(t["abbr"], t["wins"]) for t in ws["teams"]], [("LAD", 4), ("TOR", 3)])
        self.assertEqual(ws["status"]["result"], "LAD wins 4-3")
        self.assertEqual([t.get("eliminated", False) for t in ws["teams"]], [False, True])

    def test_division_series_lines_up_with_feeding_wild_card(self):
        al = self.result["bracket"]["al"]
        self.assertEqual([s["id"] for s in al["wc"]], ["F_1", "F_2"])
        # DET won F_1 and played in D_2; NYY won F_2 and played in D_1.
        self.assertEqual([s["id"] for s in al["ds"]], ["D_2", "D_1"])

    def test_wild_card_hidden_once_division_matchups_set(self):
        self.assertNotIn("show_wc", self.result["bracket"])

    def test_current_round_falls_back_to_world_series(self):
        self.assertEqual(self.result["current"], {"name": "World Series", "key": "ws"})


class InProgressPostseason(unittest.TestCase):
    """2026: Wild Card day one, PHI @ ATL live, later rounds unresolved."""

    def setUp(self):
        self.result = transform.run(load(2026))

    def test_live_game_shows_score_and_inning(self):
        series = find(self.result, "F_3")
        self.assertEqual(series["state"], "live")
        self.assertEqual(series["status"]["inning"], "Bot 3rd")
        self.assertEqual([t["score"] for t in series["teams"]], [1, 1])

    def test_scheduled_game_time_in_user_timezone(self):
        status = find(self.result, "F_2")["status"]
        self.assertEqual((status["date"], status["time"]), ("Tue 9/29", "8:00 PM"))

    def test_unset_start_time_is_tbd(self):
        status = find(self.result, "D_1")["status"]
        self.assertEqual((status["date"], status["time"]), ("Sat 10/3", "TBD"))

    def test_placeholder_teams(self):
        ds = find(self.result, "D_2")
        self.assertEqual([(t["abbr"], t.get("placeholder", False)) for t in ds["teams"]], [("HOU/CWS", True), ("CLE", False)])
        self.assertEqual([t["abbr"] for t in find(self.result, "L_1")["teams"]], ["TBD", "TBD"])

    def test_wild_card_shown_while_division_matchups_unset(self):
        self.assertTrue(self.result["bracket"]["show_wc"])

    def test_wild_card_shown_until_every_division_matchup_set(self):
        data = load(2025)
        ds = next(s for s in data["series"] if s["series"]["id"] == "D_1")
        ds["games"][0]["teams"]["away"]["team"].update(id=5528, abbreviation="NYY/BOS", placeholder=True)
        self.assertTrue(transform.run(data)["bracket"]["show_wc"])

    def test_current_round_is_wild_card(self):
        self.assertEqual(self.result["current"], {"name": "Wild Card", "key": "wc"})

    def test_probable_starters_for_scheduled_game(self):
        series = find(transform.run(with_starters_and_venues(load(2026))), "F_2")
        self.assertEqual([t["pitcher"] for t in series["teams"]], ["G. Cole", "G. Cole"])
        self.assertEqual(series["status"]["venue"], "Tropicana Field")

    def test_live_game_has_venue_but_no_probable_starters(self):
        series = find(transform.run(with_starters_and_venues(load(2026))), "F_3")
        self.assertEqual(series["status"]["venue"], "Tropicana Field")
        self.assertNotIn("pitcher", series["teams"][0])

    def test_no_venue_until_home_team_known(self):
        self.assertNotIn("venue", find(transform.run(with_starters_and_venues(load(2026))), "L_1")["status"])

    def test_unannounced_starter_omitted(self):
        self.assertNotIn("pitcher", find(self.result, "F_2")["teams"][0])

    def test_short_name(self):
        self.assertEqual(transform._short_name("George Lombard Jr."), "G. Lombard Jr.")
        self.assertEqual(transform._short_name("Ichiro"), "Ichiro")

    def test_live_game_without_inning_uses_detailed_state(self):
        data = load(2026)
        game = next(s for s in data["series"] if s["series"]["id"] == "F_3")["games"][0]
        game["linescore"] = {}
        game["status"]["detailedState"] = "Warmup"
        self.assertEqual(find(transform.run(data), "F_3")["status"]["inning"], "Warmup")


class DivisionSeriesEve(unittest.TestCase):
    """2026_ds: Division Series set, Game 1s scheduled, later rounds unresolved."""

    def setUp(self):
        self.result = transform.run(load("2026_ds"))

    def test_championship_slots_named_after_division_series(self):
        self.assertEqual([t["abbr"] for t in find(self.result, "L_1")["teams"]], ["CWS/CLE", "NYY/TB"])
        self.assertEqual([t["abbr"] for t in find(self.result, "L_2")["teams"]], ["ATL/LAD", "SD/MIL"])
        self.assertTrue(all(t["placeholder"] for t in find(self.result, "L_1")["teams"]))

    def test_wild_card_round_leaves_championship_slots_tbd(self):
        self.assertEqual([t["abbr"] for t in find(transform.run(load(2026)), "L_1")["teams"]], ["TBD", "TBD"])

    def test_world_series_slots_named_by_league(self):
        self.assertEqual([t["abbr"] for t in self.result["bracket"]["ws"]["teams"]], ["AL", "NL"])

    def test_finished_division_series_gives_its_winner(self):
        data = load("2026_ds")
        d2 = next(s for s in data["series"] if s["series"]["id"] == "D_2")
        for game in sorted(d2["games"], key=lambda g: g["seriesGameNumber"])[:3]:  # CLE (114) sweeps
            game["status"]["abstractGameState"] = "Final"
            for side in game["teams"].values():
                side["isWinner"] = side["team"]["id"] == 114
        self.assertEqual([t["abbr"] for t in find(transform.run(data), "L_1")["teams"]], ["CLE", "NYY/TB"])

    def test_probable_starters_and_venue(self):
        series = find(self.result, "D_1")
        self.assertEqual([t.get("pitcher") for t in series["teams"]], ["G. Cole", "D. Rasmussen"])
        self.assertEqual(series["status"]["venue"], "Tropicana Field")
        self.assertNotIn("venue", find(self.result, "L_1")["status"])


class WebhookLimits(unittest.TestCase):
    """The transformed result must fit TRMNL's webhook limit (5 KB standard)."""

    def test_output_under_5kb(self):
        for season in (2025, 2026, "2026_ds"):
            size = len(json.dumps(transform.run(load(season))))
            self.assertLess(size, 5000, f"{season}: {size} bytes")

    def test_output_under_5kb_with_long_starters_and_venues(self):
        data = with_starters_and_venues(load(2026), "Christopher Hernandez-Rodriguez Jr.", "UNIQLO Field at Dodger Stadium")
        size = len(json.dumps(transform.run(data)))
        self.assertLess(size, 5000, f"{size} bytes")

    def test_no_empty_values(self):
        def walk(value):
            if isinstance(value, dict):
                for v in value.values():
                    self.assertFalse(v is None or v is False or v == "", value)
                    walk(v)
            elif isinstance(value, list):
                for v in value:
                    walk(v)
        walk(transform.run(load(2026)))


class EdgeCases(unittest.TestCase):
    def test_empty_feed(self):
        result = transform.run({"trmnl": TRMNL, "series": []})
        self.assertNotIn("has_data", result)
        self.assertTrue(result["bracket"]["show_wc"])
        self.assertEqual(result["current"]["key"], "ws")

    def test_unknown_timezone_falls_back_to_offset(self):
        data = load(2026)
        data["trmnl"]["user"]["time_zone_iana"] = "Not/AZone"
        self.assertEqual(find(transform.run(data), "F_2")["status"]["time"], "8:00 PM")


if __name__ == "__main__":
    unittest.main()
