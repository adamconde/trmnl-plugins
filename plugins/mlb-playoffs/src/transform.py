"""Serverless transform: MLB Stats API postseason feed -> compact bracket model.

MLB blocks TRMNL's servers (HTTP 406 to cloud networks), so relay/mlb_relay.py
fetches ``/api/v1/schedule/postseason/series`` from a home network and posts it
to this plugin's webhook. TRMNL passes that feed, plus the ``trmnl`` namespace,
to ``run``. The returned dict replaces the merge variables available to the
templates and must fit the webhook limit (5 KB, 10 KB on TRMNL+), so None,
False and "" values are dropped:

    bracket.al / bracket.nl  {"wc": [series], "ds": [series], "cs": [series]}
    bracket.ws               series, absent before the feed has one
    bracket.show_wc          true until every Division Series team is known
    current                  {"name": round name, "key": "wc" | "ds" | "cs" | "ws"}
    updated                  local time of this refresh, e.g. "2:15 PM"
    has_data                 true when the feed has postseason series

Each series: {id, best_of, state, status, teams}
    state   "live" | "scheduled" | "final" | "tbd"
    status  {date, time, inning, game, venue, result} for the next/live game or outcome
    teams   [{id, abbr, placeholder, wins, score, pitcher, winner, eliminated}] (away, home of game 1)
            pitcher: probable starter of the next scheduled game, e.g. "G. Cole"
"""

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # runtime without tzdata; fall back to the fixed UTC offset
    ZoneInfo = None

ROUNDS = {"F": "Wild Card", "D": "Division Series", "L": "Championship Series", "W": "World Series"}
ROUND_KEYS = {"F": "wc", "D": "ds", "L": "cs", "W": "ws"}
INTERNAL_KEYS = ("round", "league", "labeled")  # used to build the bracket, not by templates
INNING_STATE = {"Top": "Top", "Middle": "Mid", "Bottom": "Bot", "End": "End"}


def run(input):
    """Build the bracket model from the MLB postseason feed.

    Args:
        input: The webhook's merge variables (the MLB feed) plus the ``trmnl`` namespace.

    Returns:
        dict: Merge variables for the templates (see module docstring).
    """
    tz = _user_tz(input.get("trmnl") or {})
    entries = sorted(input.get("series") or [], key=lambda e: e["series"]["id"])
    series = [_build_series(entry, tz) for entry in entries if entry.get("games")]

    bracket = {"ws": None}
    for league in ("al", "nl"):
        mine = [s for s in series if s["league"] == league.upper()]
        by_round = {key: [s for s in mine if s["round"] == code] for code, key in ROUND_KEYS.items() if code != "W"}
        by_round["ds"] = _order_by_feeder(by_round["ds"], by_round["wc"])
        bracket[league] = by_round
    bracket["ws"] = next((s for s in series if s["round"] == "W"), None)
    for league in ("al", "nl"):
        for cs in bracket[league]["cs"]:
            _label_open_slots(cs, bracket[league]["ds"], "TBD")
    if bracket["ws"]:
        for league in ("al", "nl"):
            for cs in bracket[league]["cs"]:
                _label_open_slots(bracket["ws"], [cs], league.upper())
    division = [s for s in series if s["round"] == "D"]
    bracket["show_wc"] = not division or any(t["placeholder"] for s in division for t in s["teams"])

    return _compact({
        "has_data": bool(series),
        "bracket": bracket,
        "current": _current_round(series),
        "updated": _fmt_time(datetime.now(timezone.utc).astimezone(tz)),
    })


def _compact(value):
    """Recursively drop None/False/"" values and internal series keys to fit the webhook limit."""
    if isinstance(value, dict):
        return {
            k: _compact(v) for k, v in value.items()
            if v is not None and v is not False and v != "" and k not in INTERNAL_KEYS
        }
    if isinstance(value, list):
        return [_compact(v) for v in value]
    return value


def _build_series(entry, tz):
    """Summarize one playoff series: teams, series record, and next/live game.

    Args:
        entry: One item of the feed's ``series`` list.
        tz: Viewer's tzinfo for formatting game times.

    Returns:
        dict: Series model (see module docstring).
    """
    games = sorted(entry["games"], key=lambda g: g.get("seriesGameNumber") or 0)
    first = games[0]
    best_of = first.get("gamesInSeries") or len(games)
    needed = best_of // 2 + 1
    round_code = entry["series"]["id"].split("_")[0]
    abbr = (first.get("seriesStatus") or {}).get("abbreviation", "")

    teams = [_team(first["teams"][side]["team"]) for side in ("away", "home")]
    by_id = {t["id"]: t for t in teams}
    for game in games:
        for side in game["teams"].values():
            if side.get("isWinner") and side["team"]["id"] in by_id:
                by_id[side["team"]["id"]]["wins"] += 1

    winner = next((t for t in teams if t["wins"] >= needed), None)
    live = next((g for g in games if g["status"]["abstractGameState"] == "Live"), None)
    upcoming = next((g for g in games if g["status"]["abstractGameState"] == "Preview"), None)

    status = {"date": "", "time": "", "inning": "", "game": "", "venue": "", "result": ""}
    if winner:
        state = "final"
        winner["winner"] = True
        loser = next(t for t in teams if t is not winner)
        loser["eliminated"] = True
        status["result"] = f"{winner['abbr']} wins {winner['wins']}-{loser['wins']}"
    elif live:
        state = "live"
        status["game"] = f"Game {live['seriesGameNumber']}"
        status["inning"] = _inning(live)
        status["venue"] = _venue(live)
        for side in live["teams"].values():
            if side["team"]["id"] in by_id:
                by_id[side["team"]["id"]]["score"] = side.get("score", 0)
    elif upcoming:
        state = "scheduled"
        status["game"] = f"Game {upcoming['seriesGameNumber']}"
        status["date"], status["time"] = _when(upcoming, tz)
        status["venue"] = _venue(upcoming)
        for side in upcoming["teams"].values():
            pitcher = (side.get("probablePitcher") or {}).get("fullName")
            if pitcher and side["team"]["id"] in by_id:
                by_id[side["team"]["id"]]["pitcher"] = _short_name(pitcher)
    else:
        state = "tbd"
        status["date"] = "TBD"

    return {
        "id": entry["series"]["id"],
        "round": round_code,
        "league": abbr[:2] if abbr[:2] in ("AL", "NL") else "",
        "best_of": best_of,
        "state": state,
        "status": status,
        "teams": teams,
    }


def _team(team):
    """Map a feed team to the template model; placeholders are unresolved slots (no logo)."""
    abbr = team.get("abbreviation") or "TBD"
    placeholder = bool(team.get("placeholder"))
    if placeholder and "/" not in abbr:  # "AL Low", "NL High", "High", ...
        abbr = "TBD"
    return {
        "id": team["id"],
        "abbr": abbr,
        "placeholder": placeholder,
        "wins": 0,
        "score": None,
        "pitcher": "",
        "winner": False,
        "eliminated": False,
    }


def _venue(game):
    """Return the game's ballpark, or "" while the home team is unresolved (MLB lists "AL Stadium", "TBD")."""
    if game["teams"]["home"]["team"].get("placeholder"):
        return ""
    return (game.get("venue") or {}).get("name", "")


def _short_name(full_name):
    """Return "G. Cole" for "Gerrit Cole" (suffixes kept: "G. Lombard Jr.")."""
    first, _, rest = full_name.partition(" ")
    return f"{first[0]}. {rest}" if rest else full_name


def _inning(game):
    """Return e.g. "Bot 3rd" for a live game, or its detailed state (Warmup, Delayed...)."""
    line = game.get("linescore") or {}
    if not line.get("currentInning"):
        return game["status"].get("detailedState", "Live")
    half = INNING_STATE.get(line.get("inningState"), line.get("inningState", ""))
    return f"{half} {line.get('currentInningOrdinal', line['currentInning'])}".strip()


def _when(game, tz):
    """Return (date, time) strings for a scheduled game; time is "TBD" if not set."""
    if game["status"].get("startTimeTBD"):
        day = datetime.strptime(game["officialDate"], "%Y-%m-%d")
        return _fmt_date(day), "TBD"
    start = datetime.fromisoformat(game["gameDate"].replace("Z", "+00:00")).astimezone(tz)
    return _fmt_date(start), _fmt_time(start)


def _fmt_date(dt):
    return f"{dt:%a} {dt.month}/{dt.day}"


def _fmt_time(dt):
    return f"{dt.hour % 12 or 12}:{dt:%M} {dt:%p}"


def _user_tz(trmnl):
    """Resolve the viewer's timezone from the trmnl namespace, defaulting to UTC."""
    user = trmnl.get("user") or {}
    if ZoneInfo and user.get("time_zone_iana"):
        try:
            return ZoneInfo(user["time_zone_iana"])
        except Exception:
            pass
    return timezone(timedelta(seconds=user.get("utc_offset") or 0))


def _order_by_feeder(division, wild_card):
    """Order Division Series to line up with the Wild Card series feeding each.

    A DS is fed by a WC series when it contains one of the WC teams, either as
    the advanced team or inside a placeholder like "HOU/CWS".
    """
    def fed_by(ds, wc):
        wc_ids = {t["id"] for t in wc["teams"]}
        wc_abbrs = {t["abbr"] for t in wc["teams"]}
        return any(t["id"] in wc_ids or set(t["abbr"].split("/")) & wc_abbrs for t in ds["teams"])

    ordered = []
    for wc in wild_card:
        ordered += [ds for ds in division if ds not in ordered and fed_by(ds, wc)]
    return ordered + [ds for ds in division if ds not in ordered]


def _label_open_slots(series, feeders, fallback):
    """Name ``series``' unresolved slots after the series feeding them, e.g. "CWS/CLE".

    MLB names these slots by seed ("AL Higher Seed"), not by feeder, so labels fill the
    open slots in bracket order. A finished feeder gives its winner; one with its own
    unresolved teams gives ``fallback``. Teams stay placeholders (no logo or dots).
    Call once per feeder (or with all feeders) after earlier slots are labeled.
    """
    known = {t["id"] for t in series["teams"] if not t["placeholder"]}
    open_slots = [t for t in series["teams"] if t["placeholder"] and not t.get("labeled")]
    for feeder in feeders:
        if not open_slots:
            return
        winner = next((t for t in feeder["teams"] if t["winner"]), None)
        if winner:
            if winner["id"] in known:
                continue
            label = winner["abbr"]
        elif any(t["placeholder"] for t in feeder["teams"]):
            label = fallback
        else:
            label = "/".join(t["abbr"] for t in feeder["teams"])
        slot = open_slots.pop(0)
        slot["abbr"], slot["labeled"] = label, True


def _current_round(series):
    """Return the earliest round with an unfinished series, else the World Series."""
    code = next((c for c in "FDLW" if any(s["round"] == c and s["state"] != "final" for s in series)), "W")
    return {"name": ROUNDS[code], "key": ROUND_KEYS[code]}
