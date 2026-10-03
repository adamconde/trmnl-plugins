#!/usr/bin/env python3
"""Relay the MLB postseason feed to the MLB Playoffs plugin's TRMNL webhook.

MLB's Stats API rejects requests from TRMNL's servers (HTTP 406 to cloud
networks), so this runs on a home machine, e.g. Synology Task Scheduler every
10 minutes. It fetches the feed and posts it to the plugin's webhook; TRMNL then
runs src/transform.py on it. Standard library only, Python 3.8+ (DSM 7).

Usage:
    TRMNL_WEBHOOK_URL=https://trmnl.com/api/custom_plugins/<uuid> python3 mlb_relay.py
    python3 mlb_relay.py --local    # post to `trmnlp serve` on localhost:4567 instead

Exits non-zero on failure (so the scheduler can alert) without posting, which
leaves the last good data on screen.
"""

import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

# `fields` trims the response to what the transform reads (~30 KB instead of ~190 KB).
# The postseason always falls within one calendar year, so `season` is the current
# year; off-season, MLB returns an empty `series` list until the bracket is set.
MLB_URL = (
    "https://statsapi.mlb.com/api/v1/schedule/postseason/series?sportId=1&season={season}"
    "&hydrate=team,linescore,seriesStatus,probablePitcher"
    "&fields=series,series,id,games,gameDate,officialDate,seriesGameNumber,gamesInSeries,status,"
    "abstractGameState,detailedState,startTimeTBD,teams,away,home,team,id,abbreviation,placeholder,"
    "score,isWinner,linescore,currentInning,currentInningOrdinal,inningState,seriesStatus,abbreviation,"
    "probablePitcher,fullName,venue,name"
)
LOCAL_WEBHOOK = "http://localhost:4567/webhook"
TIMEOUT = 20  # seconds
# trmnl.com's Cloudflare rejects Python's default User-Agent (403, error code 1010).
USER_AGENT = "trmnl-mlb-relay"


def fetch_feed():
    """Fetch and parse the current season's postseason feed from MLB.

    Returns:
        dict: The parsed feed.

    Raises:
        urllib.error.URLError, ValueError: On network failure or a response
            that isn't a feed with a ``series`` list.
    """
    url = MLB_URL.format(season=datetime.date.today().year)
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        feed = json.load(response)
    if not isinstance(feed.get("series"), list):
        raise ValueError("MLB response has no 'series' list")
    return feed


def build_request(feed, local):
    """Build the webhook POST for ``feed``.

    Args:
        feed: Parsed MLB feed.
        local: Post to a local ``trmnlp serve``, which stores the body as-is,
            instead of TRMNL, which expects it wrapped in ``merge_variables``.

    Returns:
        urllib.request.Request: The POST request.

    Raises:
        ValueError: If ``TRMNL_WEBHOOK_URL`` is missing or not HTTPS.
    """
    if local:
        url, payload = LOCAL_WEBHOOK, feed
    else:
        url = os.environ.get("TRMNL_WEBHOOK_URL", "")
        if not url.startswith("https://"):
            raise ValueError("set TRMNL_WEBHOOK_URL to the plugin's https:// webhook URL")
        payload = {"merge_variables": feed}
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    return urllib.request.Request(url, data=body, headers=headers, method="POST")


def main(argv=None):
    """Fetch the feed and post it; return the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--local", action="store_true", help=f"post to {LOCAL_WEBHOOK} (trmnlp serve)")
    args = parser.parse_args(argv)
    try:
        request = build_request(fetch_feed(), args.local)
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            print(f"posted {len(request.data)} bytes: HTTP {response.status}")
        return 0
    except urllib.error.HTTPError as e:  # e.g. 429 when over the webhook rate limit
        # Drop the last path segment: for the webhook it's the plugin UUID, a credential.
        print(f"HTTP {e.code} from {e.url.split('?')[0].rsplit('/', 1)[0]}/...: {e.read()[:200]!r}", file=sys.stderr)
    except (urllib.error.URLError, ValueError, OSError) as e:
        print(f"relay failed: {e}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
