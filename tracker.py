#!/usr/bin/env python3
"""FPL H2H league tracker for pointmaxxers 2.

Reads public Fantasy Premier League JSON endpoints, calculates the custom prize
leaderboards, writes a formatted Google Sheet, and produces a copy-ready
iMessage announcement.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from dotenv import load_dotenv

load_dotenv()

FPL_API = "https://fantasy.premierleague.com/api"
DEFAULT_LEAGUE_ID = 2147846
START_GW = 3
FINAL_GW = 38
SEASON_PRIZES = (("1st place", 70), ("2nd place", 25))
PRIZE_WINDOWS = (
    ("GW3–GW14", 3, 14, 15),
    ("GW15–GW26", 15, 26, 15),
    ("GW27–GW38", 27, 38, 15),
)


class TrackerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Manager:
    entry_id: int
    manager_name: str
    team_name: str
    official_rank: int
    rank_sort: int
    h2h_points: int
    matches_played: int
    wins: int
    draws: int
    losses: int
    points_for: int


@dataclass(frozen=True)
class H2HMatch:
    gameweek: int
    entry_1: int
    entry_1_name: str
    entry_1_manager: str
    entry_1_points: int
    entry_2: int
    entry_2_name: str
    entry_2_manager: str
    entry_2_points: int

    @property
    def result(self) -> str:
        if self.entry_1_points > self.entry_2_points:
            return f"{self.entry_1_name} win"
        if self.entry_2_points > self.entry_1_points:
            return f"{self.entry_2_name} win"
        return "Draw"

    @property
    def margin(self) -> int:
        return abs(self.entry_1_points - self.entry_2_points)


@dataclass(frozen=True)
class RankedManager:
    manager: Manager
    rank: int
    h2h_points: int
    wins: int
    draws: int
    losses: int
    points_for: int


class FPLClient:
    def __init__(self, league_id: int, timeout: int = 30) -> None:
        self.league_id = league_id
        self.timeout = timeout

    def get_json(self, path: str) -> dict[str, Any]:
        url = f"{FPL_API}/{path.lstrip('/')}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "pointmaxxers-fpl-tracker/1.0",
            },
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2**attempt)
        raise TrackerError(f"FPL request failed after 3 attempts: {url}: {last_error}")

    def events(self) -> list[dict[str, Any]]:
        return self.get_json("bootstrap-static/")["events"]

    def standings(self) -> tuple[dict[str, Any], list[Manager]]:
        page = 1
        league: dict[str, Any] | None = None
        rows: list[dict[str, Any]] = []
        while True:
            payload = self.get_json(
                f"leagues-h2h/{self.league_id}/standings/?page_standings={page}"
            )
            league = league or payload["league"]
            block = payload["standings"]
            rows.extend(block["results"])
            if not block.get("has_next"):
                break
            page += 1
        managers = [
            Manager(
                entry_id=int(row["entry"]),
                manager_name=row["player_name"],
                team_name=row["entry_name"],
                official_rank=int(row["rank"]),
                rank_sort=int(row.get("rank_sort", row["rank"])),
                h2h_points=int(row["total"]),
                matches_played=int(row["matches_played"]),
                wins=int(row["matches_won"]),
                draws=int(row["matches_drawn"]),
                losses=int(row["matches_lost"]),
                points_for=int(row["points_for"]),
            )
            for row in rows
        ]
        return league or {}, managers

    def matches(self, gameweek: int) -> list[H2HMatch]:
        page = 1
        rows: list[dict[str, Any]] = []
        while True:
            payload = self.get_json(
                "leagues-h2h-matches/league/"
                f"{self.league_id}/?page={page}&event={gameweek}"
            )
            rows.extend(payload["results"])
            if not payload.get("has_next"):
                break
            page += 1
        return [
            H2HMatch(
                gameweek=int(row["event"]),
                entry_1=int(row["entry_1_entry"]),
                entry_1_name=row["entry_1_name"],
                entry_1_manager=row["entry_1_player_name"],
                entry_1_points=int(row["entry_1_points"]),
                entry_2=int(row["entry_2_entry"]),
                entry_2_name=row["entry_2_name"],
                entry_2_manager=row["entry_2_player_name"],
                entry_2_points=int(row["entry_2_points"]),
            )
            for row in rows
            if not row.get("is_bye", False)
        ]


def completed_gameweeks(events: Iterable[dict[str, Any]]) -> list[int]:
    return sorted(
        int(event["id"])
        for event in events
        if event.get("finished") and event.get("data_checked")
    )


def current_gameweek(events: Iterable[dict[str, Any]]) -> int | None:
    for event in events:
        if event.get("is_current"):
            return int(event["id"])
    return None


def scores_by_gameweek(
    matches_by_gw: dict[int, list[H2HMatch]],
) -> dict[int, dict[int, int]]:
    scores: dict[int, dict[int, int]] = {}
    for gw, matches in matches_by_gw.items():
        scores[gw] = {}
        for match in matches:
            scores[gw][match.entry_1] = match.entry_1_points
            scores[gw][match.entry_2] = match.entry_2_points
    return scores


def simulated_standings(
    managers: list[Manager],
    matches_by_gw: dict[int, list[H2HMatch]],
    through_gw: int,
) -> list[RankedManager]:
    metrics = {
        manager.entry_id: {
            "h2h_points": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "points_for": 0,
        }
        for manager in managers
    }
    for gw in sorted(matches_by_gw):
        if gw > through_gw:
            continue
        for match in matches_by_gw[gw]:
            left = metrics[match.entry_1]
            right = metrics[match.entry_2]
            left["points_for"] += match.entry_1_points
            right["points_for"] += match.entry_2_points
            if match.entry_1_points > match.entry_2_points:
                left["wins"] += 1
                left["h2h_points"] += 3
                right["losses"] += 1
            elif match.entry_2_points > match.entry_1_points:
                right["wins"] += 1
                right["h2h_points"] += 3
                left["losses"] += 1
            else:
                left["draws"] += 1
                right["draws"] += 1
                left["h2h_points"] += 1
                right["h2h_points"] += 1

    ordered = sorted(
        managers,
        key=lambda manager: (
            -metrics[manager.entry_id]["h2h_points"],
            -metrics[manager.entry_id]["points_for"],
            manager.rank_sort,
        ),
    )
    return [
        RankedManager(
            manager=manager,
            rank=index,
            h2h_points=metrics[manager.entry_id]["h2h_points"],
            wins=metrics[manager.entry_id]["wins"],
            draws=metrics[manager.entry_id]["draws"],
            losses=metrics[manager.entry_id]["losses"],
            points_for=metrics[manager.entry_id]["points_for"],
        )
        for index, manager in enumerate(ordered, start=1)
    ]


def official_standings(managers: list[Manager]) -> list[RankedManager]:
    ordered = sorted(managers, key=lambda manager: manager.rank_sort)
    return [
        RankedManager(
            manager=manager,
            rank=manager.official_rank,
            h2h_points=manager.h2h_points,
            wins=manager.wins,
            draws=manager.draws,
            losses=manager.losses,
            points_for=manager.points_for,
        )
        for manager in ordered
    ]


def cumulative_points(
    entry_id: int,
    scores: dict[int, dict[int, int]],
    start: int,
    end: int,
) -> int:
    return sum(scores.get(gw, {}).get(entry_id, 0) for gw in range(start, end + 1))


def window_ranking(
    managers: list[Manager],
    scores: dict[int, dict[int, int]],
    start: int,
    through_gw: int,
    tiebreak_standings: list[RankedManager],
) -> list[tuple[Manager, int, int]]:
    tiebreak = {
        row.manager.entry_id: index
        for index, row in enumerate(tiebreak_standings, start=1)
    }
    ordered = sorted(
        managers,
        key=lambda manager: (
            -cumulative_points(manager.entry_id, scores, start, through_gw),
            tiebreak[manager.entry_id],
        ),
    )
    return [
        (
            manager,
            cumulative_points(manager.entry_id, scores, start, through_gw),
            tiebreak[manager.entry_id],
        )
        for manager in ordered
    ]


def standings_for_gameweek(
    managers: list[Manager],
    matches_by_gw: dict[int, list[H2HMatch]],
    gameweek: int,
    latest_finalized_gw: int,
    preview_live: bool,
) -> list[RankedManager]:
    if gameweek == latest_finalized_gw and not preview_live:
        return official_standings(managers)
    return simulated_standings(managers, matches_by_gw, gameweek)


def window_status(start: int, end: int, report_gw: int, finalized_gw: int) -> str:
    if finalized_gw >= end:
        return "Locked"
    if report_gw >= start:
        return "Live provisional" if report_gw > finalized_gw else "Provisional"
    return "Not started"


def payout_snapshot(
    managers: list[Manager],
    matches_by_gw: dict[int, list[H2HMatch]],
    report_gw: int,
    finalized_gw: int,
    preview_live: bool,
) -> tuple[list[dict[str, Any]], dict[int, dict[str, int]]]:
    scores = scores_by_gameweek(matches_by_gw)
    report_standings = standings_for_gameweek(
        managers, matches_by_gw, report_gw, finalized_gw, preview_live
    )
    awards: list[dict[str, Any]] = []
    totals = {
        manager.entry_id: {"projected": 0, "locked": 0}
        for manager in managers
    }

    if report_gw >= START_GW:
        season_locked = finalized_gw >= FINAL_GW
        for (label, amount), standing in zip(SEASON_PRIZES, report_standings[:2]):
            status = "Locked" if season_locked else (
                "Live provisional" if preview_live else "Provisional"
            )
            awards.append(
                {
                    "prize": label,
                    "manager": standing.manager,
                    "amount": amount,
                    "status": status,
                    "details": f"H2H rank {standing.rank}",
                }
            )
            totals[standing.manager.entry_id]["projected"] += amount
            if season_locked:
                totals[standing.manager.entry_id]["locked"] += amount

    for label, start, end, amount in PRIZE_WINDOWS:
        status = window_status(start, end, report_gw, finalized_gw)
        if status == "Not started":
            awards.append(
                {
                    "prize": f"{label} cumulative points",
                    "manager": None,
                    "amount": amount,
                    "status": status,
                    "details": "—",
                }
            )
            continue
        through = min(report_gw, end)
        tie_gw = end if finalized_gw >= end else report_gw
        tie_standings = standings_for_gameweek(
            managers,
            matches_by_gw,
            tie_gw,
            finalized_gw,
            preview_live and tie_gw == report_gw,
        )
        ranking = window_ranking(managers, scores, start, through, tie_standings)
        winner, points, h2h_tiebreak = ranking[0]
        awards.append(
            {
                "prize": f"{label} cumulative points",
                "manager": winner,
                "amount": amount,
                "status": status,
                "details": f"{points} FPL pts; H2H tiebreak rank {h2h_tiebreak}",
            }
        )
        totals[winner.entry_id]["projected"] += amount
        if status == "Locked":
            totals[winner.entry_id]["locked"] += amount
    return awards, totals


def active_window(gameweek: int) -> tuple[str, int, int, int]:
    for window in PRIZE_WINDOWS:
        if window[1] <= gameweek <= window[2]:
            return window
    return PRIZE_WINDOWS[-1]


def money(value: int) -> str:
    return f"${value}"


def ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def manager_weekly_statement(
    manager: Manager,
    standing: RankedManager,
    match: H2HMatch | None,
    gameweek: int,
    high_id: int | None,
    low_id: int | None,
    manager_count: int,
) -> str:
    """Return a deterministic, score-aware one-liner for one manager."""
    rng = random.Random(
        gameweek * 1000003 + DEFAULT_LEAGUE_ID + manager.entry_id * 7919
    )

    if match is None:
        return (
            f"• {manager.manager_name} — No matchup found. Even the API has "
            "chosen not to comment."
        )

    if match.entry_1 == manager.entry_id:
        score = match.entry_1_points
        opponent = match.entry_2_manager
        opponent_score = match.entry_2_points
    else:
        score = match.entry_2_points
        opponent = match.entry_1_manager
        opponent_score = match.entry_1_points

    margin = abs(score - opponent_score)
    normalized_name = " ".join(manager.manager_name.casefold().split())
    is_kellie_liu = "kellie" in normalized_name and "liu" in normalized_name

    if is_kellie_liu:
        if score > opponent_score:
            recaps = [
                f"glided past {opponent} {score}–{opponent_score} with excellent picks and even better vibes",
                f"beat {opponent} {score}–{opponent_score}; elegance, intelligence, and three thoroughly deserved points",
                f"delivered {score} points and a masterclass in making FPL look far more graceful than it is",
            ]
        elif score == opponent_score:
            recaps = [
                f"shared the points with {opponent} at {score}–{opponent_score}, remaining undefeated and universally admired",
                f"earned a {score}–{opponent_score} draw with {opponent}; composed, competitive, and still the people's champion",
                f"matched {opponent} with {score} points while once again leading the league in class",
            ]
        else:
            recaps = [
                f"scored {score} against {opponent}; the result was unkind, but the managerial vision remains impeccable",
                f"brought {score} points and immaculate vibes; sometimes the scoreboard simply fails to recognize greatness",
                f"finished on {score}, but remains the league's undisputed champion of taste, poise, and long-term potential",
            ]
    elif score == opponent_score:
        recaps = [
            f"drew {score}–{opponent_score} with {opponent}; two managers entered, neither accepted responsibility",
            f"split the points with {opponent} at {score}–{opponent_score}; a result satisfying absolutely nobody",
            f"matched {opponent} point for point at {score}; competitive neutrality has been achieved",
        ]
    elif score > opponent_score:
        if manager.entry_id == high_id:
            recaps = [
                f"dropped the GW-high {score} on {opponent}; the rest of the league has requested a financial audit",
                f"led the entire gameweek with {score} and used {opponent} as the demonstration model",
                f"posted a league-best {score}; {opponent} was unfortunately standing in the blast radius",
            ]
        elif margin <= 3:
            recaps = [
                f"escaped {opponent} {score}–{opponent_score}; three H2H points acquired under suspicious circumstances",
                f"survived {opponent} by {margin}; ugly wins remain fully legal",
                f"beat {opponent} by {margin}; the scorecard says victory and will answer no further questions",
            ]
        elif margin >= 15:
            recaps = [
                f"flattened {opponent} {score}–{opponent_score}; officially a result, unofficially a wellness check",
                f"beat {opponent} by {margin}; police are asking anyone with footage to come forward",
                f"sent {opponent} a {margin}-point invoice and demanded immediate payment",
            ]
        else:
            recaps = [
                f"handled {opponent} {score}–{opponent_score}; competent management is ruining the group-chat atmosphere",
                f"beat {opponent} by {margin} and will now describe every transfer as part of the process",
                f"collected three points from {opponent} with the irritating calm of someone whose captain returned",
            ]
    else:
        if manager.entry_id == low_id:
            recaps = [
                f"posted the GW-low {score}; witnesses confirm a full XI was allegedly selected",
                f"finished bottom of the weekly scoring with {score}; the wildcard button has begun glowing",
                f"managed a league-low {score}; FPL Towers has offered to explain the rules again",
            ]
        elif margin <= 3:
            recaps = [
                f"lost {score}–{opponent_score} to {opponent}; one honest bench decision from changing the timeline",
                f"fell to {opponent} by {margin}; a premium-grade moral victory worth zero H2H points",
                f"missed out against {opponent} by {margin}; the grievance dossier is already 14 pages",
            ]
        elif margin >= 15:
            recaps = [
                f"was dismantled by {opponent} {opponent_score}–{score}; the match report has been sealed by legal",
                f"lost to {opponent} by {margin}; thoughts, prayers, and perhaps a wildcard",
                f"spent 90 minutes inside {opponent}'s highlight reel and leaves with several lessons",
            ]
        else:
            recaps = [
                f"lost {score}–{opponent_score} to {opponent}; the underlying vibes remain elite",
                f"donated three points to {opponent}; generosity is not currently a prize category",
                f"came up {margin} short against {opponent}; the post-match xExcuses are off the charts",
            ]

    if is_kellie_liu:
        table_note = (
            f"Officially {ordinal(standing.rank)}, but comfortably 1st in the league's heart. 👑"
        )
    elif standing.rank == 1:
        table_note = "Still 1st, where the air is thin and the confidence unbearable."
    elif standing.rank <= 3:
        table_note = f"Now {ordinal(standing.rank)}; the title propaganda continues."
    elif standing.rank == manager_count:
        table_note = (
            f"Now {ordinal(standing.rank)}; 'mathematically alive' remains the official slogan."
        )
    elif standing.rank >= manager_count - 2:
        table_note = f"Now {ordinal(standing.rank)} and browsing motivational quotes."
    else:
        table_note = (
            f"Now {ordinal(standing.rank)}, safely inside the league's anonymous middle class."
        )

    return f"• {manager.manager_name} ({score}) — {rng.choice(recaps)}. {table_note}"


def build_announcement(
    league_name: str,
    gameweek: int,
    managers: list[Manager],
    matches_by_gw: dict[int, list[H2HMatch]],
    finalized_gw: int,
    preview_live: bool = False,
) -> str:
    standings = standings_for_gameweek(
        managers, matches_by_gw, gameweek, finalized_gw, preview_live
    )
    scores = scores_by_gameweek(matches_by_gw)
    gw_scores = scores.get(gameweek, {})
    by_id = {manager.entry_id: manager for manager in managers}
    score_order = sorted(
        gw_scores.items(), key=lambda item: (-item[1], by_id[item[0]].rank_sort)
    )
    awards, totals = payout_snapshot(
        managers, matches_by_gw, gameweek, finalized_gw, preview_live
    )
    label, start, end, _ = active_window(gameweek)
    tie_standings = standings
    window = window_ranking(managers, scores, start, gameweek, tie_standings)

    rng = random.Random(gameweek * 1000003 + DEFAULT_LEAGUE_ID)
    openers = [
        "The audit is complete. Several crimes were found, but all were within FPL rules.",
        "The points have been counted twice because several totals looked like cries for help.",
        "VAR reviewed the spreadsheet for clear and obvious competence. The search continues.",
        "Another gameweek has ended, so naturally everyone who won is a genius again.",
        "The numbers are in. Some managers cooked; others microwaved the captain's armband.",
        "Fourteen managers entered the gameweek. Accountability has now entered the chat.",
    ]
    closers = [
        "Please direct all appeals to the Department of Nobody Made You Captain Him.",
        "The transfer market is now open for your next carefully researched disaster.",
        "Thoughts and prayers to everyone turning one bad gameweek into a minus-eight.",
        "This concludes the weekly redistribution of hope, money, and fabricated confidence.",
        "See you next week for another episode of Captaincy Regret Simulator: Bench Points Rising.",
        "Remember: form is temporary, but the screenshot of your rank is forever.",
    ]

    status_word = "LIVE PREVIEW" if preview_live else "FINAL"
    lines = [
        f"🚨 {league_name.upper()} — GW{gameweek} {status_word} 🚨",
        "",
        rng.choice(openers),
        "",
        "👑 H2H table",
    ]
    for standing in standings[:3]:
        lines.append(
            f"{standing.rank}. {standing.manager.manager_name} "
            f"({standing.manager.team_name}) — {standing.h2h_points} pts"
        )

    if score_order:
        high_id, high_score = score_order[0]
        low_id, low_score = score_order[-1]
        lines.extend(
            [
                "",
                f"🔥 GW high score: {by_id[high_id].manager_name} — {high_score}",
                f"🫠 GW low score: {by_id[low_id].manager_name} — {low_score}",
            ]
        )
    else:
        high_id = None
        low_id = None
    matches = matches_by_gw.get(gameweek, [])
    if matches:
        biggest = max(matches, key=lambda match: match.margin)
        winner = (
            biggest.entry_1_manager
            if biggest.entry_1_points >= biggest.entry_2_points
            else biggest.entry_2_manager
        )
        loser = (
            biggest.entry_2_manager
            if biggest.entry_1_points >= biggest.entry_2_points
            else biggest.entry_1_manager
        )
        lines.append(
            f"💥 Public execution of the week: {winner} over {loser} by "
            f"{biggest.margin} points"
        )

    match_by_entry = {
        entry_id: match
        for match in matches
        for entry_id in (match.entry_1, match.entry_2)
    }
    lines.extend(["", "🎤 Manager-by-manager accountability report"])
    for standing in standings:
        lines.append(
            manager_weekly_statement(
                standing.manager,
                standing,
                match_by_entry.get(standing.manager.entry_id),
                gameweek,
                high_id,
                low_id,
                len(managers),
            )
        )

    if window:
        leader, leader_points, _ = window[0]
        gap = leader_points - window[1][1] if len(window) > 1 else leader_points
        lines.extend(
            [
                "",
                f"🏃 {label} race: {leader.manager_name} leads with "
                f"{leader_points} points ({gap} ahead)",
            ]
        )

    lines.extend(["", "💵 Current prize picture"])
    for award in awards:
        manager = award["manager"]
        if manager is not None:
            lines.append(
                f"• {award['prize']}: {manager.manager_name} — "
                f"{money(award['amount'])} ({award['status'].lower()})"
            )

    projected = sorted(
        (
            (by_id[entry_id], values["projected"])
            for entry_id, values in totals.items()
            if values["projected"]
        ),
        key=lambda item: (-item[1], item[0].rank_sort),
    )
    lines.extend(["", "🧾 Projected winnings"])
    for manager, total in projected:
        lines.append(f"• {manager.manager_name}: {money(total)}")

    lines.extend(["", rng.choice(closers)])
    return "\n".join(lines)


def matrix_dashboard(
    league_name: str,
    report_gw: int,
    finalized_gw: int,
    preview_live: bool,
    managers: list[Manager],
    standings: list[RankedManager],
    awards: list[dict[str, Any]],
    totals: dict[int, dict[str, int]],
) -> list[list[Any]]:
    by_id = {manager.entry_id: manager for manager in managers}
    rows: list[list[Any]] = [
        ["POINTMAXXERS 2 PRIZE DASHBOARD", "Manager", "Team", "Amount", "Status", "Details"],
        ["League", league_name, "", "", "", ""],
        ["Report through", f"GW{report_gw}", "", "", "", ""],
        ["Latest finalized", f"GW{finalized_gw}" if finalized_gw >= START_GW else "None yet", "", "", "", ""],
        ["Mode", "Live preview" if preview_live else "Finalized data only", "", "", "", ""],
        ["", "", "", "", "", ""],
    ]
    for award in awards:
        manager = award["manager"]
        rows.append(
            [
                award["prize"],
                manager.manager_name if manager else "—",
                manager.team_name if manager else "—",
                award["amount"],
                award["status"],
                award["details"],
            ]
        )
    rows.extend(
        [
            ["", "", "", "", "", ""],
            ["PROJECTED WINNINGS", "Manager", "Team", "Amount", "Locked", "H2H rank"],
        ]
    )
    for standing in sorted(
        standings,
        key=lambda row: (-totals[row.manager.entry_id]["projected"], row.rank),
    ):
        values = totals[standing.manager.entry_id]
        rows.append(
            [
                "Projected total",
                by_id[standing.manager.entry_id].manager_name,
                by_id[standing.manager.entry_id].team_name,
                values["projected"],
                values["locked"],
                standing.rank,
            ]
        )
    return rows


def matrices(
    league: dict[str, Any],
    managers: list[Manager],
    matches_by_gw: dict[int, list[H2HMatch]],
    report_gw: int,
    finalized_gw: int,
    preview_live: bool,
) -> dict[str, list[list[Any]]]:
    league_name = league.get("name", f"League {league.get('id', DEFAULT_LEAGUE_ID)}")
    standings = standings_for_gameweek(
        managers, matches_by_gw, report_gw, finalized_gw, preview_live
    )
    awards, totals = payout_snapshot(
        managers, matches_by_gw, report_gw, finalized_gw, preview_live
    )
    scores = scores_by_gameweek(matches_by_gw)

    output: dict[str, list[list[Any]]] = {}
    output["Dashboard"] = matrix_dashboard(
        league_name,
        report_gw,
        finalized_gw,
        preview_live,
        managers,
        standings,
        awards,
        totals,
    )
    output["H2H Standings"] = [
        ["Rank", "Manager", "Team", "H2H Points", "Played", "Won", "Drawn", "Lost", "FPL Points For"]
    ] + [
        [
            row.rank,
            row.manager.manager_name,
            row.manager.team_name,
            row.h2h_points,
            row.wins + row.draws + row.losses,
            row.wins,
            row.draws,
            row.losses,
            row.points_for,
        ]
        for row in standings
    ]

    result_rows: list[list[Any]] = [
        ["GW", "Manager 1", "Team 1", "Points 1", "Manager 2", "Team 2", "Points 2", "Result", "Margin", "Status"]
    ]
    for gw in sorted(matches_by_gw):
        for match in matches_by_gw[gw]:
            result_rows.append(
                [
                    gw,
                    match.entry_1_manager,
                    match.entry_1_name,
                    match.entry_1_points,
                    match.entry_2_manager,
                    match.entry_2_name,
                    match.entry_2_points,
                    match.result,
                    match.margin,
                    "Final" if gw <= finalized_gw else "Live preview",
                ]
            )
    output["Weekly Results"] = result_rows

    gameweeks = list(range(START_GW, report_gw + 1))
    cumulative_header = ["Overall Rank", "Manager", "Team"] + [
        f"GW{gw}" for gw in gameweeks
    ] + ["GW3–Current", "GW3–14", "GW15–26", "GW27–38"]
    overall = sorted(
        managers,
        key=lambda manager: (
            -cumulative_points(manager.entry_id, scores, START_GW, report_gw),
            next(
                i
                for i, row in enumerate(standings, start=1)
                if row.manager.entry_id == manager.entry_id
            ),
        ),
    )
    cumulative_rows = [cumulative_header]
    for rank, manager in enumerate(overall, start=1):
        cumulative_rows.append(
            [rank, manager.manager_name, manager.team_name]
            + [scores.get(gw, {}).get(manager.entry_id, 0) for gw in gameweeks]
            + [
                cumulative_points(manager.entry_id, scores, START_GW, report_gw),
                cumulative_points(manager.entry_id, scores, 3, min(report_gw, 14)),
                cumulative_points(manager.entry_id, scores, 15, min(report_gw, 26)) if report_gw >= 15 else 0,
                cumulative_points(manager.entry_id, scores, 27, min(report_gw, 38)) if report_gw >= 27 else 0,
            ]
        )
    output["Cumulative Points"] = cumulative_rows

    prize_rows: list[list[Any]] = [
        ["Window", "Status", "Rank", "Manager", "Team", "Cumulative Points", "H2H Tiebreak Rank", "Prize"]
    ]
    for label, start, end, amount in PRIZE_WINDOWS:
        status = window_status(start, end, report_gw, finalized_gw)
        if status == "Not started":
            prize_rows.append([label, status, "—", "—", "—", "—", "—", amount])
            continue
        through = min(report_gw, end)
        tie_gw = end if finalized_gw >= end else report_gw
        tie_standings = standings_for_gameweek(
            managers,
            matches_by_gw,
            tie_gw,
            finalized_gw,
            preview_live and tie_gw == report_gw,
        )
        for rank, (manager, points, h2h_rank) in enumerate(
            window_ranking(managers, scores, start, through, tie_standings), start=1
        ):
            prize_rows.append(
                [label, status, rank, manager.manager_name, manager.team_name, points, h2h_rank, amount if rank == 1 else 0]
            )
    output["Prize Windows"] = prize_rows

    payout_rows = [["H2H Rank", "Manager", "Team", "Projected Winnings", "Locked Winnings"]]
    for row in standings:
        values = totals[row.manager.entry_id]
        payout_rows.append(
            [row.rank, row.manager.manager_name, row.manager.team_name, values["projected"], values["locked"]]
        )
    output["Payout Tracker"] = payout_rows

    announcement_rows: list[list[Any]] = [["Gameweek", "Copy-ready iMessage announcement"]]
    for gw in sorted(matches_by_gw, reverse=True):
        if gw <= finalized_gw or (preview_live and gw == report_gw):
            announcement_rows.append(
                [
                    gw,
                    build_announcement(
                        league_name,
                        gw,
                        managers,
                        {key: value for key, value in matches_by_gw.items() if key <= gw},
                        min(finalized_gw, gw),
                        preview_live and gw > finalized_gw,
                    ),
                ]
            )
    output["Announcements"] = announcement_rows

    output["Rules"] = [
        ["Setting", "Value"],
        ["League", f"{league_name} ({league.get('id', DEFAULT_LEAGUE_ID)})"],
        ["Managers", len(managers)],
        ["Buy-in", "$10 per manager"],
        ["Total prize pool", "$140"],
        ["Season champion", "$70"],
        ["Season runner-up", "$25"],
        ["GW3–GW14 cumulative-points winner", "$15"],
        ["GW15–GW26 cumulative-points winner", "$15"],
        ["GW27–GW38 cumulative-points winner", "$15"],
        ["Cumulative-points tiebreak", "H2H standings at the end of the prize window"],
        ["Prize stacking", "Allowed; one manager can win multiple prizes"],
        ["Data policy", "Final announcements wait for finished=true and data_checked=true"],
    ]
    return output


def google_client(credentials_path: str | None):
    try:
        import gspread
    except ImportError as exc:
        raise TrackerError(
            "Google Sheets support requires dependencies: pip install -r requirements.txt"
        ) from exc

    raw_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw_json:
        try:
            return gspread.service_account_from_dict(json.loads(raw_json))
        except json.JSONDecodeError as exc:
            raise TrackerError("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON") from exc
    if credentials_path:
        return gspread.service_account(filename=credentials_path)
    raise TrackerError(
        "Set GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_JSON"
    )


def write_google_sheet(
    sheet_id: str,
    data: dict[str, list[list[Any]]],
    credentials_path: str | None,
) -> None:
    client = google_client(credentials_path)
    try:
        spreadsheet = client.open_by_key(sheet_id)
    except Exception as exc:
        raise TrackerError(
            "Could not open the Google Sheet. Confirm GOOGLE_SHEET_ID and share "
            "the sheet with the service account's client_email as Editor."
        ) from exc

    existing = {worksheet.title: worksheet for worksheet in spreadsheet.worksheets()}
    for title, values in data.items():
        cols = max((len(row) for row in values), default=1)
        rows = max(len(values) + 5, 25)
        if title in existing:
            worksheet = existing[title]
            worksheet.clear()
            if worksheet.row_count < rows or worksheet.col_count < max(cols, 2):
                worksheet.resize(
                    rows=max(worksheet.row_count, rows),
                    cols=max(worksheet.col_count, cols, 2),
                )
        else:
            worksheet = spreadsheet.add_worksheet(
                title=title, rows=rows, cols=max(cols, 2)
            )
        padded = [row + [""] * (cols - len(row)) for row in values]
        if padded:
            worksheet.update(values=padded, range_name="A1")
        worksheet.freeze(rows=1)
        last_col = column_name(cols)
        worksheet.format(
            f"A1:{last_col}1",
            {
                "backgroundColor": {"red": 0.07, "green": 0.16, "blue": 0.30},
                "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}, "bold": True},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            },
        )
        if title == "Announcements":
            worksheet.format(
                f"B2:B{max(len(values), 2)}",
                {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"},
            )
        if title == "Dashboard":
            worksheet.format(
                f"D2:D{max(len(values), 2)}",
                {"numberFormat": {"type": "CURRENCY", "pattern": "$0"}},
            )
        elif title == "Payout Tracker":
            worksheet.format(
                f"D2:E{max(len(values), 2)}",
                {"numberFormat": {"type": "CURRENCY", "pattern": "$0"}},
            )
        elif title == "Prize Windows":
            worksheet.format(
                f"H2:H{max(len(values), 2)}",
                {"numberFormat": {"type": "CURRENCY", "pattern": "$0"}},
            )
        if title != "Announcements":
            try:
                worksheet.columns_auto_resize(0, cols)
            except Exception:
                pass


def column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--league-id",
        type=int,
        default=int(os.environ.get("FPL_LEAGUE_ID", DEFAULT_LEAGUE_ID)),
    )
    parser.add_argument("--sheet-id", default=os.environ.get("GOOGLE_SHEET_ID"))
    parser.add_argument(
        "--credentials",
        default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
        help="Path to a Google service-account JSON key",
    )
    parser.add_argument(
        "--no-sheet",
        action="store_true",
        help="Fetch and calculate without updating Google Sheets",
    )
    parser.add_argument(
        "--preview-live",
        action="store_true",
        help="Include the current unfinished gameweek as a clearly labeled preview",
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    client = FPLClient(args.league_id)
    events = client.events()
    finalized = [gw for gw in completed_gameweeks(events) if gw >= START_GW]
    finalized_gw = max(finalized, default=START_GW - 1)
    report_gw = finalized_gw
    if args.preview_live:
        current = current_gameweek(events)
        if current is not None and current >= START_GW:
            report_gw = current

    if report_gw < START_GW:
        print("No finalized gameweek exists from GW3 onward yet.")
        print("Use --preview-live to inspect the current unfinished gameweek.")
        return 0

    league, managers = client.standings()
    if int(league.get("start_event", START_GW)) != START_GW:
        raise TrackerError(
            f"League start_event is {league.get('start_event')}, expected {START_GW}."
        )
    if len(managers) != 14:
        raise TrackerError(f"Expected 14 managers, found {len(managers)}.")
    expected_played = max(0, finalized_gw - START_GW + 1)
    if any(manager.matches_played != expected_played for manager in managers):
        raise TrackerError(
            "FPL has finalized the gameweek, but the H2H standings have not "
            "finished updating yet. Run the tracker again later."
        )

    matches_by_gw = {
        gw: client.matches(gw) for gw in range(START_GW, report_gw + 1)
    }
    for gw, matches in matches_by_gw.items():
        if len(matches) != 7:
            raise TrackerError(f"Expected 7 H2H matches in GW{gw}, found {len(matches)}.")

    data = matrices(
        league,
        managers,
        matches_by_gw,
        report_gw,
        finalized_gw,
        args.preview_live and report_gw > finalized_gw,
    )
    latest_announcement = data["Announcements"][1][1]
    print(latest_announcement)

    if not args.no_sheet:
        if not args.sheet_id:
            raise TrackerError("Set GOOGLE_SHEET_ID or pass --sheet-id.")
        write_google_sheet(args.sheet_id, data, args.credentials)
        print("\nGoogle Sheet updated successfully.")
    return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except TrackerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
