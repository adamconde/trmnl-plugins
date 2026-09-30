"""Serverless transform: Oura API v2 daily collections -> dashboard tiles.

TRMNL polls the URLs in settings.yml with the user's OAuth token. Only the
collections the selected metrics need are polled (SOURCE_METRICS; the Liquid in
polling_url makes the same choice), in SOURCES order, and the responses arrive as
``IDX_0``, ``IDX_1``, ... (or unwrapped when only one URL is polled), plus the
``trmnl`` namespace. A URL that failed (missing scope, expired subscription)
arrives as an empty or error object and its metrics are skipped.

Returned merge variables:

    tiles     [tile] for the selected metrics that have data, in catalog order
    has_data  true when at least one tile has data
    date      viewer's today, e.g. "Tue, Sep 29"
    updated   local time of this refresh, e.g. "7:15 AM"

Each tile: {key, label, value, size, unit, status, note, headline, stale, ring, pct, segments, bars}
    value     center text ("84", "7h 32m", "Normal")
    size      font size for ``value`` in the ring's 100-unit SVG box, small enough to fit inside it
    ring      "arc" (``pct`` 0-100 filled), "segments" (``segments`` [{offset, length, filled}]
              in pathLength-100 units), or "plain" (outline only)
    status    word under the ring ("Optimal", "62% of goal"), may be absent
    note      comparison with the rest of the week ("+4 vs 7-day avg"), may be absent
    headline  sentence for the featured metric, in Oura's voice ("Your sleep is good")
    stale     weekday of the data when it isn't today's ("Mon"), may be absent
    bars      7 days ending today, oldest first: {day, height 0-100, current, empty}
"""

import math
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # runtime without tzdata; fall back to the fixed UTC offset
    ZoneInfo = None

# Oura collections in the order of the polling_url lines in settings.yml, with the
# metrics that need each one (keep the conditions in polling_url in sync).
SOURCE_METRICS = {
    "daily_readiness": ("readiness", "temperature"),
    "daily_sleep": ("sleep",),
    "daily_activity": ("activity", "steps"),
    "daily_stress": ("stress",),
    "sleep": ("total_sleep", "resting_hr", "hrv"),
    "daily_resilience": ("resilience",),
    "daily_spo2": ("spo2",),
    "daily_cardiovascular_age": ("cardio_age",),
    "vo2_max": ("vo2_max",),
}
SOURCES = tuple(SOURCE_METRICS)
CATALOG = (
    "readiness", "sleep", "activity", "stress", "resilience", "total_sleep", "steps",
    "resting_hr", "hrv", "spo2", "cardio_age", "vo2_max", "temperature",
)
DEFAULT_METRICS = ("readiness", "sleep", "activity", "stress")
LABELS = {
    "readiness": "Readiness", "sleep": "Sleep", "activity": "Activity", "stress": "Stress",
    "resilience": "Resilience", "total_sleep": "Total sleep", "steps": "Steps",
    "resting_hr": "Resting HR", "hrv": "HRV", "spo2": "SpO2", "cardio_age": "Cardio age",
    "vo2_max": "VO2 max", "temperature": "Temperature",
}
SCORES = ("readiness", "sleep", "activity")
STRESS_LEVELS = ("restored", "normal", "stressful")
RESILIENCE_LEVELS = ("limited", "adequate", "solid", "strong", "exceptional")
SLEEP_TARGET_SECONDS = 8 * 3600
DAYS = 7
SEGMENT_GAP = 4  # gap between ring segments, in pathLength-100 units
# Ring center text, in the ring's 100-unit SVG box: at most this big (the metric's icon sits
# above it), and no wider than TEXT_WIDTH (inside the ring's inner edge at radius 40).
TEXT_MAX_SIZE = 34
TEXT_WIDTH = 62
# Advance widths (em) of Inter at weight 400, the framework's value font, measured in Chrome.
# Characters not listed count as 0.65em, about the widest common glyph.
CHAR_EM = {
    **dict.fromkeys("0123456789+−", 0.645), ",": 0.269, ".": 0.269, " ": 0.25, "%": 0.844,
    "a": 0.518, "b": 0.565, "c": 0.523, "d": 0.565, "e": 0.536, "f": 0.28, "g": 0.565, "h": 0.547,
    "i": 0.206, "l": 0.206, "m": 0.839, "n": 0.547, "o": 0.549, "p": 0.565, "r": 0.322, "s": 0.475,
    "t": 0.28, "u": 0.547, "v": 0.512, "A": 0.662, "E": 0.58, "L": 0.535, "N": 0.71, "R": 0.632, "S": 0.614,
}


def run(input):
    """Build dashboard tiles for the selected metrics from the polled Oura responses.

    Args:
        input: Polled responses as ``IDX_<n>`` (see SOURCES) plus the ``trmnl`` namespace.

    Returns:
        dict: Merge variables for the templates (see module docstring).
    """
    trmnl = input.get("trmnl") or {}
    now = datetime.now(timezone.utc).astimezone(_user_tz(trmnl))
    selected = _selected(trmnl)
    series = _series(_polled_documents(input, selected))

    tiles = [t for t in (_tile(key, series.get(key) or {}, now.date()) for key in selected) if t]
    return _compact({
        "has_data": bool(tiles),
        "tiles": tiles,
        "date": f"{now:%a, %b} {now.day}",
        "updated": f"{now.hour % 12 or 12}:{now:%M} {now:%p}",
    })


def _selected(trmnl):
    """Return the metric keys chosen in the Metrics field, in catalog order, or the defaults.

    Accepts a list or a comma-separated string, since the stored form isn't documented.
    """
    values = ((trmnl.get("plugin_settings") or {}).get("custom_fields_values") or {}).get("metrics")
    if isinstance(values, str):
        values = values.split(",")
    chosen = {str(v).strip() for v in values or ()}
    return [key for key in CATALOG if key in chosen] or list(DEFAULT_METRICS)


def _polled_documents(input, selected):
    """Map every source to its documents, matching responses to the sources polled for ``selected``.

    TRMNL numbers the responses IDX_0, IDX_1, ... in polling order, but passes a single
    response as-is, without the IDX_0 wrapper.
    """
    polled = [s for s in SOURCES if set(SOURCE_METRICS[s]) & set(selected)]
    if len(polled) == 1:
        responses = {polled[0]: input}
    else:
        responses = {name: input.get(f"IDX_{i}") for i, name in enumerate(polled)}
    return {name: _documents(responses.get(name)) for name in SOURCES}


def _documents(response):
    """Return the documents of one polled response, or [] for a failed request."""
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict) and d.get("day")]


def _series(docs):
    """Map each metric to {date: value}, one value per day."""
    def by_day(documents, pick):
        out = {}
        for doc in documents:
            value = pick(doc)
            if value is not None:
                out[date.fromisoformat(doc["day"][:10])] = value
        return out

    # A day can have several sleep periods (naps); use the long sleep, else the longest.
    main = {}
    for doc in docs["sleep"]:
        rank = (doc.get("type") == "long_sleep", doc.get("total_sleep_duration") or 0)
        if doc["day"] not in main or rank > main[doc["day"]][0]:
            main[doc["day"]] = (rank, doc)
    sleeps = [doc for _, doc in main.values()]

    return {
        "readiness": by_day(docs["daily_readiness"], lambda d: d.get("score")),
        "temperature": by_day(docs["daily_readiness"], lambda d: d.get("temperature_deviation")),
        "sleep": by_day(docs["daily_sleep"], lambda d: d.get("score")),
        "activity": by_day(docs["daily_activity"], lambda d: d.get("score")),
        "steps": by_day(docs["daily_activity"], lambda d: d if d.get("steps") is not None else None),
        "stress": by_day(docs["daily_stress"], lambda d: d if d.get("day_summary") or d.get("stress_high") is not None else None),
        "resilience": by_day(docs["daily_resilience"], lambda d: d.get("level") if d.get("level") in RESILIENCE_LEVELS else None),
        "total_sleep": by_day(sleeps, lambda d: d.get("total_sleep_duration")),
        "resting_hr": by_day(sleeps, lambda d: d.get("lowest_heart_rate")),
        "hrv": by_day(sleeps, lambda d: d.get("average_hrv")),
        "spo2": by_day(docs["daily_spo2"], lambda d: (d.get("spo2_percentage") or {}).get("average")),
        "cardio_age": by_day(docs["daily_cardiovascular_age"], lambda d: d.get("vascular_age")),
        "vo2_max": by_day(docs["vo2_max"], lambda d: d.get("vo2_max")),
    }


def _tile(key, values, today):
    """Build one tile from a metric's {date: value}, or None when the week has no data.

    The tile shows the latest day up to ``today`` (sleep-derived metrics only appear
    after the morning sync, so early in the day that is yesterday's).
    """
    days = [today - timedelta(days=i) for i in range(DAYS - 1, -1, -1)]
    shown = next((d for d in reversed(days) if d in values), None)
    if shown is None:
        return None
    current = values[shown]
    others = [values[d] for d in days if d in values and d != shown]
    number = _NUMBER.get(key, lambda v: v)  # the numeric value used for bars and averages
    tile = {
        "key": key,
        "label": LABELS[key],
        "ring": "plain",
        "stale": None if shown == today else f"{shown:%a}",
        "bars": _bars(days, {d: number(v) for d, v in values.items()}, shown),
    }
    tile.update(_FORMAT[key](current, [number(v) for v in others]))
    tile["size"] = _text_size(tile["value"])
    tile["headline"] = _headline(key, tile)
    return tile


def _score(value, others):
    return {"value": str(value), "ring": "arc", "pct": _clamp(value), "status": _band(value), "note": _delta(value, others)}


def _stress(doc, others):
    summary = doc.get("day_summary")
    stress, recovery = doc.get("stress_high"), doc.get("recovery_high")
    parts = [f"{_duration(stress)} stressed" if stress is not None else None,
             f"{_duration(recovery)} restored" if recovery is not None else None]
    return {
        "value": summary.capitalize() if summary else _duration(stress),
        "ring": "segments",
        "segments": _segments(len(STRESS_LEVELS), [STRESS_LEVELS.index(summary)] if summary else []),
        "status": None if summary else "So far today",
        "note": " · ".join(p for p in parts if p),
    }


def _resilience(level, others):
    index = RESILIENCE_LEVELS.index(level)
    return {
        "value": level.capitalize(),
        "ring": "segments",
        "segments": _segments(len(RESILIENCE_LEVELS), range(index + 1)),
        "status": f"Level {index + 1} of {len(RESILIENCE_LEVELS)}",
    }


def _total_sleep(seconds, others):
    return {
        "value": _duration(seconds),
        "ring": "arc",
        "pct": _clamp(100 * seconds / SLEEP_TARGET_SECONDS),
        "status": f"{round(100 * seconds / SLEEP_TARGET_SECONDS)}% of 8h",
        "note": _delta(seconds, others, _duration),
    }


def _steps(doc, others):
    target, done = doc.get("target_meters"), doc.get("equivalent_walking_distance")
    out = {"value": f"{doc['steps']:,}", "note": _delta(doc["steps"], others, lambda v: f"{v:,}")}
    if target and done is not None:  # Oura's daily activity goal, as walking distance
        out.update(ring="arc", pct=_clamp(100 * done / target), status=f"{round(100 * done / target)}% of goal")
    return out


def _measure(unit, digits=0, signed=False):
    """Formatter for a plain measurement shown in an outline ring."""
    def fmt(value, others):
        shown = _round(value, digits, signed)
        return {"value": shown, "unit": unit, "note": _delta(value, others, lambda v: _round(v, digits))}
    return fmt


def _spo2(value, others):
    return {"value": str(round(value)), "unit": "%", "ring": "arc", "pct": _clamp(value),
            "note": _delta(value, others)}


_FORMAT = {
    "readiness": _score, "sleep": _score, "activity": _score,
    "stress": _stress, "resilience": _resilience, "total_sleep": _total_sleep, "steps": _steps,
    "resting_hr": _measure("bpm"), "hrv": _measure("ms"), "spo2": _spo2,
    "cardio_age": _measure("yrs"), "vo2_max": _measure("ml/kg"),
    "temperature": _measure("°C", digits=1, signed=True),
}
_NUMBER = {
    "stress": lambda d: d.get("stress_high") or 0,
    "resilience": lambda level: RESILIENCE_LEVELS.index(level) + 1,
    "steps": lambda d: d["steps"],
}


def _headline(key, tile):
    """Sentence for the featured metric, in the style of Oura's cards ("Your readiness is good")."""
    value, status, unit = tile["value"], tile.get("status"), tile.get("unit")
    if key in SCORES:
        return f"Your {key} needs attention" if status == "Pay attention" else f"Your {key} is {status.lower()}"
    if key == "resilience":
        return f"Your resilience is {value.lower()}"
    if key == "stress":
        return f"{value} of stress so far" if status else f"Your day was {value.lower()}"
    if key == "total_sleep":
        return f"You slept {value}"
    if key == "steps":
        return f"{value} steps"
    return f"{value}{'' if unit in ('%', '°C') else ' '}{unit}"


def _band(score):
    """Oura's contributor bands for a 0-100 score."""
    if score >= 85:
        return "Optimal"
    if score >= 70:
        return "Good"
    if score >= 60:
        return "Fair"
    return "Pay attention"


def _delta(value, others, fmt=lambda v: str(round(v))):
    """Describe ``value`` against the mean of the week's other days, e.g. "+4 vs 7-day avg"."""
    if not others:
        return None
    diff = value - sum(others) / len(others)
    shown = fmt(abs(diff))
    if shown in ("0", "0.0", "0m", "0h 0m"):
        return "Same as 7-day avg"
    return f"{'+' if diff > 0 else '−'}{shown} vs 7-day avg"


def _bars(days, numbers, shown):
    """7-day trend bars, scaled between the week's low (30) and high (100) so small changes show."""
    present = [numbers[d] for d in days if d in numbers]
    low, high = min(present), max(present)
    bars = []
    for d in days:
        if d not in numbers:
            bars.append({"day": f"{d:%a}", "height": 0, "empty": True})
            continue
        height = 65 if high == low else 30 + 70 * (numbers[d] - low) / (high - low)
        bars.append({"day": f"{d:%a}", "height": round(height), "current": d == shown})
    return bars


def _segments(count, filled):
    """Ring segments starting at 12 o'clock, each {offset, length, filled} in pathLength-100 units."""
    step = 100 / count
    return [{"offset": round(-(i * step + SEGMENT_GAP / 2), 2), "length": round(step - SEGMENT_GAP, 2),
             "filled": i in filled} for i in range(count)]


def _text_size(text):
    """Font size that fits ``text`` across the ring's inner circle, capped at TEXT_MAX_SIZE."""
    em = sum(CHAR_EM.get(c, 0.65) for c in text)
    return math.floor(10 * min(TEXT_MAX_SIZE, TEXT_WIDTH / em)) / 10 if em else TEXT_MAX_SIZE  # round down to stay inside


def _duration(seconds):
    minutes = round((seconds or 0) / 60)
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"


def _round(value, digits=0, signed=False):
    text = f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"
    return text.replace("-", "−")


def _clamp(pct):
    return max(0, min(100, round(pct)))


def _compact(value):
    """Recursively drop None/False/"" values to keep the payload small."""
    if isinstance(value, dict):
        return {k: _compact(v) for k, v in value.items() if v is not None and v is not False and v != ""}
    if isinstance(value, list):
        return [_compact(v) for v in value]
    return value


def _user_tz(trmnl):
    """Resolve the viewer's timezone from the trmnl namespace, defaulting to UTC."""
    user = trmnl.get("user") or {}
    if ZoneInfo and user.get("time_zone_iana"):
        try:
            return ZoneInfo(user["time_zone_iana"])
        except Exception:
            pass
    return timezone(timedelta(seconds=user.get("utc_offset") or 0))
