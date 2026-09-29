# MLB Playoffs

MLB postseason bracket for TRMNL: team logos, series record, next game date/time (TBD when unscheduled), and live score + inning for games in progress.

## How it works

MLB's Stats API returns HTTP 406 to requests from cloud networks, including TRMNL's servers and Serverless machines (since about 2026-09-27). So TRMNL can't fetch the data itself; a machine on your home network relays it:

```text
home NAS (every 10 min)                        TRMNL
relay/mlb_relay.py --- MLB feed (~22 KB) --->  webhook -> src/transform.py -> templates
```

- **Relay:** [relay/mlb_relay.py](relay/mlb_relay.py) fetches the postseason series feed from the public [MLB Stats API](https://statsapi.mlb.com) (no API key) and posts it to the plugin's webhook. Standard library only, Python 3.8+. If MLB fails, it posts nothing, so the last good data stays on screen, and it exits non-zero.
- **Transform:** [src/transform.py](src/transform.py) runs on TRMNL Serverless when the webhook arrives. It counts series wins, finds each series' live or next game, formats times in the TRMNL account's timezone, and orders Division Series next to the Wild Card series feeding them. Its output (~2.5 KB) must fit the webhook limit of 5 KB (10 KB on TRMNL+), so it drops empty values.
- **Layouts:**
  - `full`: the whole bracket, AL on the left, NL on the right, World Series in the middle. Once every Division Series team is known, the Wild Card columns drop out (7 columns become 5).
  - `half_horizontal`, `half_vertical`, `quadrant`: the current round only (earliest round with an unfinished series).

Card legend: filled dots = series wins (dots = wins needed), large number = live game score, bold = series winner, gray = eliminated. Unresolved slots show the possible teams (`HOU/CWS`) or `TBD`. "Updated" is when TRMNL last received data; if it stops advancing, check the relay.

## Relay setup (Synology NAS)

1. Copy your webhook URL from the plugin's settings page on trmnl.com (**Webhook URL**, `https://trmnl.com/api/custom_plugins/<uuid>`). Treat it like a password: anyone with it can post to your plugin.
2. Optional: test from any home machine first:

   ```bash
   read -rs TRMNL_WEBHOOK_URL && export TRMNL_WEBHOOK_URL   # paste the URL, press Enter
   python3 relay/mlb_relay.py                                # expect: posted ... bytes: HTTP 200
   ```

3. Copy `relay/mlb_relay.py` to the NAS, e.g. `/volume1/scripts/mlb_relay.py`.
4. In DSM: **Control Panel → Task Scheduler → Create → Scheduled Task → User-defined script**.
   - **General:** name it `TRMNL MLB relay`. Pick a regular user rather than `root`; the script only needs network access and read access to its own file.
   - **Schedule:** daily, first run 00:00, repeat **every 10 minutes**, last run 23:50. That's 6 posts an hour, under the webhook limit of 12 (30 on TRMNL+).
   - **Task Settings:** tick **Send run details by email → only when the script terminates abnormally**, and set the script to:

     ```bash
     TRMNL_WEBHOOK_URL='https://trmnl.com/api/custom_plugins/<uuid>' python3 /volume1/scripts/mlb_relay.py
     ```

5. Select the task and **Run** it once, then confirm "Updated" advances on the plugin.
6. After the World Series, disable the task.

## Development

```bash
bin/trmnlp serve                     # http://localhost:4567 (no data until the next line)
python3 relay/mlb_relay.py --local   # post live MLB data to the local server
bin/trmnlp lint
python3 -m unittest discover tests   # transform and relay tests
```

Preview times use `time_zone` in `.trmnlp.yml`. To preview recorded data, post a fixture: `curl -X POST -H "Content-Type: application/json" --data-binary @tests/fixtures/postseason_2025.json localhost:4567/webhook`. To refresh fixtures, save the relay's `MLB_URL` response (fill in `{season}`) into `tests/fixtures/`. Tests assert on game state captured at recording time, so update the expectations as well.

## Next season

Nothing to change: the relay requests the current year's postseason. Off-season, MLB returns no series and the plugin shows "No postseason schedule yet" until the bracket is published (usually late September). Leave the NAS task running year-round, or disable it after the World Series and re-enable it each fall.
