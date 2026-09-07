# Pointmaxxers 2 — FPL H2H tracker

This tracker is configured for the 14-manager FPL H2H league **pointmaxxers 2**
(league ID `2147846`), with scoring beginning in GW3.

It reads the public FPL JSON endpoints, rebuilds every result from GW3 onward,
updates a Google Sheet, and generates one copy-ready iMessage announcement per
gameweek. Normal runs only publish data after FPL marks a gameweek both
`finished` and `data_checked`; `--preview-live` is available for clearly labeled
live previews.

## Prize rules

| Prize | Amount |
|---|---:|
| H2H champion | $70 |
| H2H runner-up | $25 |
| Most cumulative FPL points, GW3–GW14 | $15 |
| Most cumulative FPL points, GW15–GW26 | $15 |
| Most cumulative FPL points, GW27–GW38 | $15 |
| **Total** | **$140** |

Prizes stack: one manager can win more than one prize. A cumulative-points tie
is broken by the H2H standings at the end of that prize window. For a live
window, the current H2H standings are used provisionally.

## What appears in Google Sheets

- `Dashboard`: current prize holders and projected/locked winnings.
- `H2H Standings`: official or reconstructed league table.
- `Weekly Results`: every H2H matchup and score.
- `Cumulative Points`: weekly points and all three prize-window totals.
- `Prize Windows`: complete ranking for each cumulative-points race.
- `Payout Tracker`: projected and locked winnings by manager.
- `Announcements`: newest copy-ready iMessage announcement first.
- `Rules`: the league configuration used by the script.

The script rewrites these tabs from FPL data on each run. That makes updates
idempotent: rerunning it does not duplicate rows or announcements.

## One-time Google setup

1. Create a blank Google Sheet and copy its ID. In a URL such as
   `https://docs.google.com/spreadsheets/d/ABC123/edit`, the ID is `ABC123`.
2. In Google Cloud, create or select a project.
3. Enable the **Google Sheets API** and **Google Drive API**.
4. Create a service account and download its JSON key.
5. Open the JSON key and copy the `client_email` value.
6. Share the blank Google Sheet with that email as an **Editor**.

Keep the JSON key private. Never commit it to Git.

## Run locally

Python 3.10 or newer is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export GOOGLE_SHEET_ID="your_sheet_id"
export GOOGLE_APPLICATION_CREDENTIALS="/absolute/path/service-account.json"
python tracker.py
```

To inspect the calculations without touching Google Sheets:

```bash
python tracker.py --no-sheet
```

At the time this package was built (September 7, 2026), GW3 was unfinished.
This command produces a live, explicitly labeled preview whenever a gameweek is
in progress:

```bash
python tracker.py --no-sheet --preview-live
```

For a preview that also updates the sheet, omit `--no-sheet`.

## Automate with GitHub Actions

The included workflow checks every six hours. It exits harmlessly until a GW3+
gameweek is finalized, then rebuilds the sheet. Add these repository secrets:

- `GOOGLE_SHEET_ID`: the Google Sheet ID.
- `GOOGLE_SERVICE_ACCOUNT_JSON`: the complete contents of the JSON key.

Push the project to a private GitHub repository and enable Actions. The latest
text will be in cell `Announcements!B2`; copy that cell into the iMessage chat.
The schedule is deliberately not tied to Sundays because FPL gameweeks can end
on Mondays, weekdays, or after rescheduled fixtures.

## Commands

```text
python tracker.py [--league-id ID] [--sheet-id ID]
                  [--credentials PATH] [--no-sheet] [--preview-live]
```

`FPL_LEAGUE_ID` defaults to `2147846`. The code validates that the API still
reports a GW3 start and exactly 14 managers before changing the spreadsheet.

## Notes

- The public FPL endpoints are not formally versioned, so the script fails with
  a clear error instead of silently producing a misleading sheet if the payload
  shape changes.
- The H2H ranking displayed during an unfinished live preview is simulated from
  current matchup scores. Final runs use the official FPL standings.
- No FPL login or password is required.
