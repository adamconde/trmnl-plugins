# Oura

Oura Ring scores on TRMNL, drawn as rings rather than bare numbers, with a 7-day trend under each one. You pick which metrics to show; the default is Readiness, Sleep, Activity and Stress.

## What each tile shows

| Metric | Ring | Center | Under the ring |
| --- | --- | --- | --- |
| Readiness, Sleep, Activity | arc filled to the score (0-100) | score | Oura's band: Optimal (85+), Good (70-84), Fair (60-69), Pay attention (<60, inverted) |
| Stress | 3 segments (restored, normal, stressful), current one filled | day summary, or time stressed so far | time stressed and restored |
| Resilience | 5 segments, filled up to the level | level (Limited … Exceptional) | "Level n of 5" |
| Total sleep | arc toward 8 hours | e.g. `7h 32m` | % of 8h |
| Steps | arc toward Oura's daily activity goal | step count | % of goal |
| SpO2 | arc filled to the average % | % | |
| Resting HR, HRV, Cardio age, VO2 max, Temperature | outline ring | value and unit | |

Below each ring, 7 bars show the last week, oldest first. The day in the ring is solid, the other days are outlined, and a flat tick means no data that day. Bars are scaled between the week's low and high, so they show direction rather than absolute level. The full-screen view with 4 or fewer tiles also shows how the day compares with the week's average (`+3 vs 7-day avg`).

Sleep-based numbers (readiness, sleep, total sleep, resting HR, HRV) only exist after you open the Oura app and sync in the morning. Until then, a tile shows the latest earlier day and names it (`Good · Mon`). Resting HR and HRV come from the night's main sleep; naps are ignored.

Layouts:

- `full`: up to 4 tiles in one large row, or 5-8 in two rows.
- `half_horizontal`: up to 5 in a row.
- `half_vertical`: 2 columns. With 5-6 tiles, the status and bars are dropped to keep the rings readable.
- `quadrant`: up to 4 small rings.

Metrics beyond a layout's limit are left off, in the order listed in the Metrics field.

## How it works

```text
TRMNL (every 60 min, OAuth bearer token)                     TRMNL Serverless
9 Oura API v2 collections, last 7 days -> IDX_0..IDX_8 -> src/transform.py -> tiles -> templates
```

- **Polling:** [src/settings.yml](src/settings.yml) lists one URL per Oura collection (readiness, daily sleep, activity, stress, sleep periods, resilience, SpO2, cardiovascular age, VO2 max), each with `fields=` so the responses stay small. They're always polled, whatever you select. The date window runs from 7 days ago to tomorrow (UTC), which covers your last 7 days in any timezone.
- **Transform:** [src/transform.py](src/transform.py) picks the selected metrics, finds each metric's latest day up to your local today (TRMNL account timezone), and computes ring fill, labels and bar heights. A collection that failed (for example, a scope you didn't grant) just drops its tiles.
- **Templates:** [src/shared.liquid](src/shared.liquid) draws the rings and bars as inline SVG in black only, so they stay sharp on 1-bit screens.

## Setup

Oura retired personal access tokens in December 2025, so the plugin signs in with OAuth using your own Oura API application. It's free, and an app can serve up to 10 users without Oura's approval.

1. **Add the plugin on TRMNL** and open its settings. Under OAuth, copy the **redirect URL** TRMNL shows.
2. **Create an Oura API application** at [cloud.ouraring.com/oauth/applications](https://cloud.ouraring.com/oauth/applications):
   - Redirect URI: the URL from step 1. Add `http://localhost:4567/oauth/callback` too if you'll preview locally.
   - Scopes: `daily`, `spo2`, `heart_health`.
   - Note the **Client ID** and **Client Secret**.
3. **Back in TRMNL**, paste the Client ID and Client Secret into the plugin's OAuth settings (the authorize/token URLs and scopes are prefilled from [src/settings.yml](src/settings.yml); the Oura provider template fills the same values). Save, then **Connect** and approve the requested data on Oura's consent screen.
4. Pick your **Metrics**, or leave the field empty for the default four.

If you leave a scope unchecked on Oura's consent screen, the metrics that need it (SpO2 needs `spo2`; Cardio age and VO2 max need `heart_health`) don't appear. Everything else still works. To add a scope later, disconnect and connect again.

A 403 from Oura usually means the Oura membership has lapsed; the plugin then shows "No Oura data yet".

## Development

```bash
bin/trmnlp serve                     # http://localhost:4567
bin/trmnlp lint
python3 -m unittest discover tests   # transform tests
```

**Preview with sample data** (no Oura account needed). Post a synthetic week to the local server:

```bash
python3 tests/sample.py | curl -X POST -H "Content-Type: application/json" --data-binary @- localhost:4567/webhook
```

The next poll replaces it. Change `custom_fields.metrics` in [.trmnlp.yml](.trmnlp.yml) to preview other selections.

**Preview with your own data:** export your app's credentials before `bin/trmnlp serve`, then click **Connect account** in the preview:

```bash
read -rs TRMNL_OAUTH_CLIENT_ID && export TRMNL_OAUTH_CLIENT_ID
read -rs TRMNL_OAUTH_CLIENT_SECRET && export TRMNL_OAUTH_CLIENT_SECRET
```

The Docker wrapper doesn't pass environment variables into the container, so this needs the `trmnl_preview` gem (or add `--env TRMNL_OAUTH_CLIENT_ID --env TRMNL_OAUTH_CLIENT_SECRET` to the `docker run` in [bin/trmnlp](bin/trmnlp)). trmnlp keeps the tokens in its cache directory, never in this repo.

To add a metric: add its option to `metrics` in `src/settings.yml`, add it to `CATALOG`, `LABELS` and `_FORMAT` in `src/transform.py` (plus a polling URL and `SOURCES` entry if it needs a new collection; keep both in the same order), and add a test.

## Version history

The version appears at the end of **About This Plugin** (`author_bio` in [src/settings.yml](src/settings.yml)). Bump it there and add a line here with each release.

- **1.0.0** (2026-09-29): first release. Readiness, Sleep, Activity and Stress by default, plus Resilience, Total sleep, Steps, Resting HR, HRV, SpO2, Cardio age, VO2 max and Temperature. Ring gauges with 7-day trend bars in all four layouts.
