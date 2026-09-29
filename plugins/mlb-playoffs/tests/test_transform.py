"""Tests for src/transform.py against recorded MLB Stats API responses.

Fixtures are MLB feed responses (relay/mlb_relay.py MLB_URL) for a finished postseason (2025)
and one captured mid-Wild Card round with a game in progress (2026).

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

    def test_live_game_without_inning_uses_detailed_state(self):
        data = load(2026)
        game = next(s for s in data["series"] if s["series"]["id"] == "F_3")["games"][0]
        game["linescore"] = {}
        game["status"]["detailedState"] = "Warmup"
        self.assertEqual(find(transform.run(data), "F_3")["status"]["inning"], "Warmup")


class WebhookLimits(unittest.TestCase):
    """The transformed result must fit TRMNL's webhook limit (5 KB standard)."""

    def test_output_under_5kb(self):
        for season in (2025, 2026):
            size = len(json.dumps(transform.run(load(season))))
            self.assertLess(size, 5000, f"{season}: {size} bytes")

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
