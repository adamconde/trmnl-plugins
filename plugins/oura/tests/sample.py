"""Synthetic Oura API responses shaped like the polled merge variables (IDX_0 .. IDX_8).

Oura's sandbox also needs an OAuth token, so these follow the v2 OpenAPI schemas with
the ``fields`` filters from settings.yml. Days are relative to ``today`` so the
transform, which reads the clock, always sees a current week.

Preview in trmnlp without connecting OAuth:
    python3 tests/sample.py | curl -X POST -H "Content-Type: application/json" --data-binary @- localhost:4567/webhook
"""

import json
from datetime import date, timedelta

READINESS = [78, 82, 71, 88, 90, 76, 84]
SLEEP_SCORE = [74, 80, 68, 86, 91, 79, 82]
ACTIVITY = [81, 77, 92, 85, 70, 88, 64]
STEPS = [9120, 7433, 12876, 10254, 5311, 11002, 4210]
STRESS = ["normal", "stressful", "normal", "restored", "normal", "normal", ""]  # "": summary not in yet
RESILIENCE = ["adequate", "solid", "solid", "solid", "strong", "strong", "solid"]
TOTAL_SLEEP = [25200, 26820, 22500, 28440, 29100, 26100, 27120]
LOWEST_HR = [53, 51, 56, 50, 49, 52, 51]
HRV = [41, 45, 36, 48, 52, 44, 46]


def sample(today=None):
    """Return the nine polled responses for the week ending ``today``, keyed IDX_0 .. IDX_8."""
    today = today or date.today()
    days = [(today - timedelta(days=6 - i)).isoformat() for i in range(7)]

    def docs(values, build):
        return {"data": [dict(id=f"doc-{d}", day=d, **build(v)) for d, v in zip(days, values) if v is not None],
                "next_token": None}

    sleep = docs(TOTAL_SLEEP, lambda s: {"type": "long_sleep", "total_sleep_duration": s})
    for doc, hr, hrv in zip(sleep["data"], LOWEST_HR, HRV):
        doc.update(lowest_heart_rate=hr, average_hrv=hrv)
    sleep["data"].append({"id": "nap", "day": days[-1], "type": "sleep", "total_sleep_duration": 1800,
                          "lowest_heart_rate": 60, "average_hrv": 30})

    return {
        "IDX_0": docs(READINESS, lambda s: {"score": s, "temperature_deviation": round((s - 80) / 40, 2)}),
        "IDX_1": docs(SLEEP_SCORE, lambda s: {"score": s}),
        "IDX_2": docs(list(zip(ACTIVITY, STEPS)), lambda v: {
            "score": v[0], "steps": v[1], "equivalent_walking_distance": v[1] * 0.8, "target_meters": 8000}),
        "IDX_3": docs(STRESS, lambda s: {"day_summary": s or None, "stress_high": 5400 if s == "stressful" else 2700,
                                         "recovery_high": 3600}),
        "IDX_4": sleep,
        "IDX_5": docs(RESILIENCE, lambda lvl: {"level": lvl, "contributors": {
            "sleep_recovery": 70, "daytime_recovery": 60, "stress": 55}}),
        "IDX_6": docs([96.8, 97.2, 95.9, 97.5, 98.0, 96.4, 97.1], lambda v: {"spo2_percentage": {"average": v}}),
        "IDX_7": docs([None, None, 38, None, None, 37, None], lambda v: {"vascular_age": v}),
        "IDX_8": docs([None, 44, None, None, 45, None, None], lambda v: {"vo2_max": v}),
    }


if __name__ == "__main__":
    print(json.dumps(sample()))
