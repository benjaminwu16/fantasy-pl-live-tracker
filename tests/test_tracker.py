#!/usr/bin/env python3
"""Tests for the POINTMAXXERS FPL tracker OpenAI announcement integration."""

from __future__ import annotations

import io
import json
import os
import unittest
from unittest.mock import patch

import tracker


class FakeHTTPResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def make_manager(
    entry_id: int,
    name: str,
    team: str,
    rank: int,
    h2h_points: int = 3,
    wins: int = 1,
    draws: int = 0,
    losses: int = 0,
    points_for: int = 60,
) -> tracker.Manager:
    return tracker.Manager(
        entry_id=entry_id,
        manager_name=name,
        team_name=team,
        official_rank=rank,
        rank_sort=rank,
        h2h_points=h2h_points,
        matches_played=wins + draws + losses,
        wins=wins,
        draws=draws,
        losses=losses,
        points_for=points_for,
    )


def make_ranked(manager: tracker.Manager, rank: int | None = None) -> tracker.RankedManager:
    return tracker.RankedManager(
        manager=manager,
        rank=manager.official_rank if rank is None else rank,
        h2h_points=manager.h2h_points,
        wins=manager.wins,
        draws=manager.draws,
        losses=manager.losses,
        points_for=manager.points_for,
    )


def make_match(
    left: tracker.Manager,
    right: tracker.Manager,
    left_score: int,
    right_score: int,
    gameweek: int = 3,
) -> tracker.H2HMatch:
    return tracker.H2HMatch(
        gameweek=gameweek,
        entry_1=left.entry_id,
        entry_1_name=left.team_name,
        entry_1_manager=left.manager_name,
        entry_1_points=left_score,
        entry_2=right.entry_id,
        entry_2_name=right.team_name,
        entry_2_manager=right.manager_name,
        entry_2_points=right_score,
    )


def responses_payload(statements: list[dict[str, object]]) -> dict[str, object]:
    return {
        "id": "resp_test",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"statements": statements}),
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 30,
            "total_tokens": 130,
        },
    }


class TrackerOpenAITests(unittest.TestCase):
    def setUp(self) -> None:
        self.colton = make_manager(1, "Colton Simon", "Rashford Goat FC", 1, points_for=69)
        self.david = make_manager(
            2,
            "David Kim",
            "David Team",
            14,
            h2h_points=0,
            wins=0,
            losses=1,
            points_for=30,
        )
        self.match = make_match(self.colton, self.david, 69, 30)
        self.standings = [make_ranked(self.colton), make_ranked(self.david)]
        self.match_by_entry = {1: self.match, 2: self.match}

    def clean_openai_env(self) -> dict[str, str]:
        return {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("OPENAI_") and key != "USE_OPENAI_LLM"
        }

    def test_extract_openai_output_text(self) -> None:
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "hello "},
                        {"type": "output_text", "text": "world"},
                    ],
                },
                {"type": "web_search_call", "content": []},
            ]
        }
        self.assertEqual(tracker.extract_openai_output_text(payload), "hello world")

    def test_manager_prompt_context_locks_verified_facts(self) -> None:
        context = tracker.manager_prompt_context(
            self.colton,
            make_ranked(self.colton),
            self.match,
            high_id=self.colton.entry_id,
            low_id=self.david.entry_id,
            manager_count=14,
        )
        self.assertEqual(context["score"], 69)
        self.assertEqual(context["opponent_score"], 30)
        self.assertEqual(context["result"], "win")
        self.assertEqual(context["margin"], 39)
        self.assertEqual(
            context["fact_clause"],
            "posted a league-best 69 and beat David Kim 69–30",
        )
        self.assertEqual(
            context["table_note"],
            "Still 1st, where the air is thin and the confidence unbearable.",
        )

    def test_kellie_context_is_always_favorable(self) -> None:
        kellie = make_manager(
            3,
            "Kellie Liu",
            "Kellie Team",
            8,
            h2h_points=0,
            wins=0,
            losses=1,
            points_for=59,
        )
        eddie = make_manager(4, "Eddie Wu", "Boo Wu", 3, points_for=66)
        match = make_match(kellie, eddie, 59, 66)
        context = tracker.manager_prompt_context(
            kellie,
            make_ranked(kellie),
            match,
            high_id=None,
            low_id=None,
            manager_count=14,
        )
        self.assertEqual(context["result"], "loss")
        self.assertIn("Never roast Kellie", context["tone_instruction"])
        self.assertIn("1st in the league's heart", context["table_note"])

    def test_openai_disabled_does_not_make_http_request(self) -> None:
        env = self.clean_openai_env()
        with patch.dict(os.environ, env, clear=True), patch.object(tracker, "urlopen") as mocked:
            result = tracker.openai_manager_statements(
                self.standings,
                self.match_by_entry,
                gameweek=3,
                high_id=1,
                low_id=2,
            )
        self.assertEqual(result, {})
        mocked.assert_not_called()

    def test_missing_api_key_falls_back_without_http_request(self) -> None:
        env = self.clean_openai_env()
        env["USE_OPENAI_LLM"] = "true"
        with patch.dict(os.environ, env, clear=True), patch.object(tracker, "urlopen") as mocked:
            result = tracker.openai_manager_statements(
                self.standings,
                self.match_by_entry,
                gameweek=3,
                high_id=1,
                low_id=2,
            )
        self.assertEqual(result, {})
        mocked.assert_not_called()

    def test_openai_request_uses_responses_api_and_structured_output(self) -> None:
        captured: dict[str, object] = {}
        payload = responses_payload(
            [
                {"entry_id": 1, "punchline": "the league has requested a financial audit"},
                {"entry_id": 2, "punchline": "the press conference has been cancelled on legal advice"},
            ]
        )

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeHTTPResponse(json.dumps(payload).encode("utf-8"))

        env = self.clean_openai_env()
        env.update(
            {
                "USE_OPENAI_LLM": "true",
                "OPENAI_API_KEY": "sk-test-not-real",
                "OPENAI_MODEL": "gpt-5.6-sol",
                "OPENAI_WEB_SEARCH": "false",
            }
        )
        with patch.dict(os.environ, env, clear=True), patch.object(
            tracker, "urlopen", side_effect=fake_urlopen
        ):
            result = tracker.openai_manager_statements(
                self.standings,
                self.match_by_entry,
                gameweek=3,
                high_id=1,
                low_id=2,
            )

        self.assertEqual(set(result), {1, 2})
        self.assertIn("posted a league-best 69 and beat David Kim 69–30", result[1])
        self.assertIn("the league has requested a financial audit", result[1])
        self.assertIn("finished bottom of the weekly scoring with 30", result[2])

        request = captured["request"]
        self.assertEqual(request.full_url, tracker.OPENAI_RESPONSES_API)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer sk-test-not-real")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "gpt-5.6-sol")
        self.assertFalse(body["store"])
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertNotIn("tools", body)

    def test_web_search_can_be_enabled_and_is_capped(self) -> None:
        payload = responses_payload(
            [
                {"entry_id": 1, "punchline": "the spreadsheet has entered witness protection"},
                {"entry_id": 2, "punchline": "FPL Towers is declining all comment"},
            ]
        )
        captured_body: dict[str, object] = {}

        def fake_urlopen(request, timeout):
            captured_body.update(json.loads(request.data.decode("utf-8")))
            return FakeHTTPResponse(json.dumps(payload).encode("utf-8"))

        env = self.clean_openai_env()
        env.update(
            {
                "USE_OPENAI_LLM": "true",
                "OPENAI_API_KEY": "sk-test-not-real",
                "OPENAI_WEB_SEARCH": "true",
                "OPENAI_WEB_SEARCH_CONTEXT_SIZE": "low",
                "OPENAI_MAX_TOOL_CALLS": "2",
            }
        )
        with patch.dict(os.environ, env, clear=True), patch.object(
            tracker, "urlopen", side_effect=fake_urlopen
        ):
            result = tracker.openai_manager_statements(
                self.standings,
                self.match_by_entry,
                gameweek=3,
                high_id=1,
                low_id=2,
            )

        self.assertEqual(set(result), {1, 2})
        self.assertEqual(captured_body["max_tool_calls"], 2)
        self.assertEqual(
            captured_body["tools"],
            [{"type": "web_search_preview", "search_context_size": "low"}],
        )

    def test_invalid_manager_item_is_omitted_but_valid_item_survives(self) -> None:
        payload = responses_payload(
            [
                {"entry_id": 1, "punchline": "the league has retained outside counsel"},
                {"entry_id": 2, "punchline": "the wildcard button has blinked 3 times"},
            ]
        )

        env = self.clean_openai_env()
        env.update({"USE_OPENAI_LLM": "true", "OPENAI_API_KEY": "sk-test-not-real"})
        with patch.dict(os.environ, env, clear=True), patch.object(
            tracker,
            "urlopen",
            return_value=FakeHTTPResponse(json.dumps(payload).encode("utf-8")),
        ):
            result = tracker.openai_manager_statements(
                self.standings,
                self.match_by_entry,
                gameweek=3,
                high_id=1,
                low_id=2,
            )

        self.assertIn(1, result)
        self.assertNotIn(2, result)

    def test_build_announcement_uses_ai_when_supplied(self) -> None:
        ai_statement = {
            1: "posted a league-best 69 and beat David Kim 69–30; the league has retained outside counsel. Still 1st, where the air is thin and the confidence unbearable.",
            2: "finished bottom of the weekly scoring with 30 and lost to Colton Simon 30–69; the press conference has been cancelled on legal advice. Now 2nd; the title propaganda continues.",
        }
        with patch.object(tracker, "openai_manager_statements", return_value=ai_statement):
            announcement = tracker.build_announcement(
                "Pointmaxxers 2",
                gameweek=3,
                managers=[self.colton, self.david],
                matches_by_gw={3: [self.match]},
                finalized_gw=3,
                preview_live=False,
                use_openai_llm=True,
            )

        self.assertIn("🎤 Manager-by-manager accountability report", announcement)
        self.assertIn("the league has retained outside counsel", announcement)
        self.assertIn("the press conference has been cancelled on legal advice", announcement)

    def test_build_announcement_uses_deterministic_fallback_when_ai_empty(self) -> None:
        with patch.object(tracker, "openai_manager_statements", return_value={}):
            announcement = tracker.build_announcement(
                "Pointmaxxers 2",
                gameweek=3,
                managers=[self.colton, self.david],
                matches_by_gw={3: [self.match]},
                finalized_gw=3,
                preview_live=False,
                use_openai_llm=True,
            )

        self.assertIn("• Colton Simon (69) —", announcement)
        self.assertIn("• David Kim (30) —", announcement)


if __name__ == "__main__":
    unittest.main(verbosity=2)
