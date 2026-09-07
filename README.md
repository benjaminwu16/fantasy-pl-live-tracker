# Pointmaxxers 2 — FPL H2H tracker

This tracker is configured for the 14-manager FPL H2H league **pointmaxxers 2**
(league ID `2147846`), with scoring beginning in GW3.

It reads the public FPL JSON endpoints, rebuilds every result from GW3 onward,
updates a Google Sheet, and generates one copy-ready iMessage announcement per
gameweek.

Normal runs only publish data after FPL marks a gameweek both `finished` and
`data_checked`. Use `--preview-live` for a clearly labeled live preview of an
unfinished gameweek.

The latest announcement can optionally use the **OpenAI Responses API** to
generate stochastic manager-by-manager jokes. All scores, opponents, results,
standings, prize calculations, and factual matchup text remain deterministic
Python data. If the OpenAI request fails or returns invalid output, the tracker
falls back to the built-in deterministic joke templates.

## Prize rules

| Prize | Amount |
|---|---:|
| H2H champion | $70 |
| H2H runner-up | $25 |
| Most cumulative FPL points, GW3–GW14 | $15 |
| Most cumulative FPL points, GW15–GW26 | $15 |
| Most cumulative FPL points, GW27–GW38 | $15 |
| **Total** | **$140** |

Prizes stack: one manager can win more than one prize.

A cumulative-points tie is broken by the H2H standings at the end of that prize
window. For a live window, the current H2H standings are used provisionally.

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

Only the **latest** announcement is eligible for OpenAI-generated punchlines.
Older gameweeks are rebuilt with deterministic templates, so rerunning the
tracker does not spend API credits regenerating the full announcement history.

## One-time Google setup

1. Create a blank Google Sheet and copy its ID. In a URL such as

   `https://docs.google.com/spreadsheets/d/ABC123/edit`

   the ID is `ABC123`.

2. In Google Cloud, create or select a project.

3. Enable the **Google Sheets API** and **Google Drive API**.

4. Create a service account and download its JSON key.

5. Open the JSON key and copy the `client_email` value.

6. Share the blank Google Sheet with that email as an **Editor**.

Keep the JSON key private. Never commit it to Git.

## Optional OpenAI setup

OpenAI API billing is separate from a ChatGPT Plus subscription. If you want the
hosted model to write the weekly manager punchlines, fund the API account with
prepaid credits and create an API key.

The tracker does **not** require the `openai` Python package; it calls the
Responses API directly over HTTPS.

### 1. Buy prepaid API credits

In the OpenAI API Platform:

1. Open your API organization's **Billing** page.
2. Select **Add payment details**.
3. Choose an initial prepaid credit amount.
4. Review **Use auto-reload** before confirming the purchase.
5. Turn auto-reload **off** if you want strictly manual prepaid spending.

As of September 2026, OpenAI documents a **$5 minimum initial prepaid purchase**
and notes that auto-reload is enabled by default during setup. Purchased API
credits expire after one year and are non-refundable.

Official documentation:

- https://help.openai.com/en/articles/8264644-setting-up-and-managing-prepaid-api-billing

A prepaid balance is not an instantaneous hard spending cutoff: billing
processing can lag slightly, so a small negative balance can occasionally
appear before access stops.

### 2. Create a project and API key

For cleaner usage tracking, create a dedicated API project such as
`pointmaxxers-fpl`.

Then create a secret API key from that project's **API Keys** page. Save the
secret when it is shown; OpenAI does not display the full key again later.

Official documentation:

- https://help.openai.com/en/articles/9186755-managing-your-work-in-the-api-platform-with-projects
- https://help.openai.com/en/articles/4936850-where-do-i-find-my-openai-api-key

Never commit the API key to Git or paste it into source code.

## Local configuration

Python 3.10 or newer is recommended.

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The tracker automatically loads a simple `.env` file located beside
`tracker.py`, so the easiest setup is to create:

```text
.env
```

with:

```bash
FPL_LEAGUE_ID=2147846

GOOGLE_SHEET_ID=your_sheet_id
GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/service-account.json

USE_OPENAI_LLM=true
OPENAI_API_KEY=your_openai_api_key

OPENAI_MODEL=gpt-5.6-sol
OPENAI_TEMPERATURE=0.85
OPENAI_REASONING_EFFORT=none
OPENAI_SHOW_USAGE=true

OPENAI_WEB_SEARCH=false
```

Then run:

```bash
python tracker.py
```

Environment variables already defined in your shell take precedence over values
in `.env`.

If you prefer shell exports instead of `.env`:

```bash
export GOOGLE_SHEET_ID="your_sheet_id"
export GOOGLE_APPLICATION_CREDENTIALS="/absolute/path/service-account.json"
export USE_OPENAI_LLM="true"
export OPENAI_API_KEY="your_openai_api_key"

python tracker.py
```

### Keep secrets out of Git

At minimum, add these to `.gitignore`:

```text
.env
service-account.json
__pycache__/
.venv/
```

If the OpenAI key or Google service-account key is ever committed or shared,
rotate it immediately.

## OpenAI announcement behavior

When `USE_OPENAI_LLM=true`, the latest manager-by-manager report uses the OpenAI
Responses API.

The architecture is intentionally constrained:

```text
FPL API
   ↓
Python calculates scores, opponents, results, standings, and prizes
   ↓
Python constructs authoritative factual matchup clauses
   ↓
OpenAI generates only the short comedic punchline
   ↓
Python validates the generated output
   ↓
Invalid/missing lines fall back to deterministic templates
```

The model therefore does not control the league facts.

The default model is:

```bash
OPENAI_MODEL=gpt-5.6-sol
```

The main optional settings are:

| Variable | Default | Purpose |
|---|---|---|
| `USE_OPENAI_LLM` | false | Enable hosted OpenAI punchlines |
| `OPENAI_API_KEY` | — | Secret API key |
| `OPENAI_MODEL` | `gpt-5.6-sol` | Model used for punchlines |
| `OPENAI_TEMPERATURE` | `0.85` | Creativity/randomness |
| `OPENAI_REASONING_EFFORT` | `none` | Reasoning effort |
| `OPENAI_TIMEOUT` | `180` | API timeout in seconds |
| `OPENAI_MAX_OUTPUT_TOKENS` | `1400` | Maximum response tokens |
| `OPENAI_SHOW_USAGE` | false | Print token usage to stderr |
| `OPENAI_WEB_SEARCH` | false | Allow current web context |
| `OPENAI_WEB_SEARCH_CONTEXT_SIZE` | `low` | Web-search context size |
| `OPENAI_MAX_TOOL_CALLS` | `2` | Maximum web tool calls |
| `OPENAI_PROJECT_ID` | — | Optional explicit project header |
| `OPENAI_ORGANIZATION` | — | Optional explicit organization header |

If `USE_OPENAI_LLM` is false, the tracker uses only the built-in deterministic
templates.

If `USE_OPENAI_LLM` is true but `OPENAI_API_KEY` is missing, exhausted, invalid,
or the request otherwise fails, the script prints a warning and continues with
the deterministic fallback.

## Optional web context

Web search is **off by default** to keep API usage predictable.

To allow the model to use genuinely current Premier League/FPL context as a
cultural reference in its jokes:

```bash
OPENAI_WEB_SEARCH=true
```

The tracker still treats its own FPL data as authoritative. Web results may
enrich a joke, but they cannot override a score, matchup, result, rank, or prize
calculation.

The default web configuration is intentionally conservative:

```bash
OPENAI_WEB_SEARCH_CONTEXT_SIZE=low
OPENAI_MAX_TOOL_CALLS=2
```

For the lowest-cost setup, leave web search disabled.

## Run locally

Normal run:

```bash
python tracker.py
```

Inspect the calculations and announcement without touching Google Sheets:

```bash
python tracker.py --no-sheet
```

Generate a clearly labeled preview for the current unfinished gameweek:

```bash
python tracker.py --no-sheet --preview-live
```

For a live preview that also updates the sheet:

```bash
python tracker.py --preview-live
```

## Tests

Run the test suite with:

```bash
python3 -m unittest -v test_tracker.py
```

The OpenAI integration tests mock the network request, so running the test suite
does **not** spend API credits.

The tests cover behavior such as:

- OpenAI disabled.
- Missing API key.
- Structured Responses API output.
- Optional web-search configuration.
- Generated-output validation.
- Deterministic fallback behavior.

## Automate with GitHub Actions

The included workflow checks every six hours. It exits harmlessly until a GW3+
gameweek is finalized, then rebuilds the sheet.

For the Google Sheet integration, add these repository secrets:

- `GOOGLE_SHEET_ID`: the Google Sheet ID.
- `GOOGLE_SERVICE_ACCOUNT_JSON`: the complete contents of the Google service-account JSON key.

If you also want AI-generated punchlines in GitHub Actions, add:

- `OPENAI_API_KEY`: the OpenAI API project key.

The workflow must expose the following environment variable to `tracker.py`:

```text
USE_OPENAI_LLM=true
```

If you want web context in automated reports, also expose:

```text
OPENAI_WEB_SEARCH=true
```

Keep web search off if you want the lowest and most predictable API spend.

Push the project to a private GitHub repository and enable Actions. The latest
text will be in cell `Announcements!B2`; copy that cell into the iMessage chat.

The schedule is deliberately not tied to Sundays because FPL gameweeks can end
on Mondays, weekdays, or after rescheduled fixtures.

## Commands

```text
python tracker.py [--league-id ID] [--sheet-id ID]
                  [--credentials PATH] [--no-sheet] [--preview-live]
```

`FPL_LEAGUE_ID` defaults to `2147846`.

The code validates that the API still reports a GW3 start and exactly 14
managers before changing the spreadsheet.

## Notes

- The public FPL endpoints are not formally versioned, so the script fails with
  a clear error instead of silently producing a misleading sheet if the payload
  shape changes.

- The H2H ranking displayed during an unfinished live preview is simulated from
  current matchup scores. Final runs use the official FPL standings.

- No FPL login or password is required.

- Google credentials and the OpenAI API key should be treated as secrets.

- ChatGPT Plus and OpenAI API billing are separate.

- The OpenAI integration is optional; league calculations do not depend on it.
