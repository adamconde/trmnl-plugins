"""Tests for src/transform.py against synthetic Oura responses (tests/sample.py).

Run from the plugin directory: python3 -m unittest discover tests
"""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import transform  # noqa: E402
from sample import sample  # noqa: E402

TZ = "America/New_York"


def today():
    return datetime.now(ZoneInfo(TZ)).date()


def run(metrics=None, data=None):
    """Run the transform on ``data`` (default: the sample week) with the given Metrics selection."""
    data = dict(sample(today()) if data is None else data)
    settings = {"custom_fields_values": {"metrics": metrics}} if metrics is not None else {}
    data["trmnl"] = {"user": {"time_zone_iana": TZ, "utc_offset": -14400}, "plugin_settings": settings}
    return transform.run(data)


def tiles(result):
    return {t["key"]: t for t in result["tiles"]}


class Selection(unittest.TestCase):
    def test_default_is_the_four_scores(self):
        self.assertEqual([t["key"] for t in run()["tiles"]], ["readiness", "sleep", "activity", "stress"])

    def test_empty_selection_uses_defaults(self):
        self.assertEqual(len(run(metrics=[])["tiles"]), 4)

    def test_catalog_order_and_unknown_keys_ignored(self):
        result = run(metrics=["hrv", "bogus", "readiness", "steps"])
        self.assertEqual([t["key"] for t in result["tiles"]], ["readiness", "steps", "hrv"])

    def test_comma_separated_string(self):
        self.assertEqual([t["key"] for t in run(metrics="sleep, spo2")["tiles"]], ["sleep", "spo2"])

    def test_every_metric_builds(self):
        self.assertEqual(len(run(metrics=list(transform.CATALOG))["tiles"]), len(transform.CATALOG))


class Scores(unittest.TestCase):
    def setUp(self):
        self.t = tiles(run())

    def test_readiness_ring_and_band(self):
        r = self.t["readiness"]
        self.assertEqual((r["value"], r["ring"], r["pct"], r["status"]), ("84", "arc", 84, "Good"))
        self.assertNotIn("long", r)
        self.assertNotIn("stale", r)

    def test_delta_against_other_days(self):
        # other days average (78+82+71+88+90+76)/6 = 80.8
        self.assertEqual(self.t["readiness"]["note"], "+3 vs 7-day avg")
        self.assertEqual(self.t["activity"]["note"], "−18 vs 7-day avg")

    def test_bars_scale_between_week_low_and_high(self):
        bars = self.t["readiness"]["bars"]
        self.assertEqual(len(bars), 7)
        self.assertEqual(bars[2]["height"], 30)   # 71, the low
        self.assertEqual(bars[4]["height"], 100)  # 90, the high
        self.assertTrue(bars[-1]["current"])
        self.assertEqual(sum(1 for b in bars if b.get("current")), 1)

    def test_bands(self):
        self.assertEqual([transform._band(s) for s in (85, 84, 70, 69, 60, 59)],
                         ["Optimal", "Good", "Good", "Fair", "Fair", "Pay attention"])


class OtherMetrics(unittest.TestCase):
    def setUp(self):
        self.t = tiles(run(metrics=list(transform.CATALOG)))

    def test_stress_in_progress_shows_time_so_far(self):
        s = self.t["stress"]
        self.assertEqual((s["value"], s["status"], s["ring"], s["long"]), ("45m", "So far today", "segments", True))
        self.assertFalse(any(seg.get("filled") for seg in s["segments"]))
        self.assertEqual(s["note"], "45m stressed · 1h 0m restored")

    def test_stress_summary_fills_its_segment(self):
        data = sample(today())
        data["IDX_3"]["data"][-1]["day_summary"] = "stressful"
        s = tiles(run(metrics=["stress"], data=data))["stress"]
        self.assertEqual(s["value"], "Stressful")
        self.assertEqual([bool(seg.get("filled")) for seg in s["segments"]], [False, False, True])

    def test_resilience_fills_up_to_level(self):
        r = self.t["resilience"]
        self.assertEqual((r["value"], r["status"], r["long"]), ("Solid", "Level 3 of 5", True))
        self.assertEqual([bool(seg.get("filled")) for seg in r["segments"]], [True, True, True, False, False])
        self.assertEqual(r["segments"][0], {"offset": -2.0, "length": 16.0, "filled": True})

    def test_total_sleep_uses_main_sleep_not_nap(self):
        s = self.t["total_sleep"]
        self.assertEqual((s["value"], s["pct"], s["status"]), ("7h 32m", 94, "94% of 8h"))
        self.assertEqual(self.t["resting_hr"]["value"], "51")
        self.assertEqual(self.t["hrv"]["value"], "46")

    def test_steps_ring_is_goal_progress(self):
        s = self.t["steps"]
        self.assertEqual((s["value"], s["pct"], s["status"]), ("4,210", 42, "42% of goal"))

    def test_measurements(self):
        self.assertEqual((self.t["spo2"]["value"], self.t["spo2"]["unit"]), ("97", "%"))
        self.assertEqual((self.t["temperature"]["value"], self.t["temperature"]["unit"]), ("+0.1", "°C"))
        self.assertEqual(self.t["resting_hr"]["ring"], "plain")

    def test_sparse_metric_shows_latest_day_as_stale(self):
        c = self.t["cardio_age"]
        self.assertEqual(c["value"], "37")
        self.assertEqual(c["stale"], f"{today() - timedelta(days=1):%a}")
        self.assertEqual(sum(1 for b in c["bars"] if b.get("empty")), 5)


class MissingData(unittest.TestCase):
    def test_failed_requests_skip_their_tiles(self):
        data = sample(today())
        data["IDX_0"] = {}                                   # failed poll
        data["IDX_1"] = {"detail": "Unauthorized"}           # error body
        result = run(data=data)
        self.assertEqual([t["key"] for t in result["tiles"]], ["activity", "stress"])

    def test_nothing_polled(self):
        result = run(data={})
        self.assertNotIn("has_data", result)
        self.assertEqual(result["tiles"], [])
        self.assertIn("updated", result)

    def test_data_older_than_a_week_is_ignored(self):
        data = sample(today() - timedelta(days=10))
        self.assertEqual(run(data=data)["tiles"], [])


if __name__ == "__main__":
    unittest.main()
