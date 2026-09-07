import unittest

from tracker import (
    H2HMatch,
    Manager,
    PRIZE_WINDOWS,
    SEASON_PRIZES,
    build_announcement,
    column_name,
    cumulative_points,
    payout_snapshot,
    scores_by_gameweek,
    simulated_standings,
    window_ranking,
)


def manager(entry_id, name, rank_sort):
    return Manager(
        entry_id=entry_id,
        manager_name=name,
        team_name=f"{name} FC",
        official_rank=rank_sort,
        rank_sort=rank_sort,
        h2h_points=0,
        matches_played=0,
        wins=0,
        draws=0,
        losses=0,
        points_for=0,
    )


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.managers = [manager(1, "Alice", 1), manager(2, "Bob", 2)]
        self.matches = {
            3: [H2HMatch(3, 1, "Alice FC", "Alice", 50, 2, "Bob FC", "Bob", 40)],
            4: [H2HMatch(4, 1, "Alice FC", "Alice", 30, 2, "Bob FC", "Bob", 40)],
        }

    def test_prize_pool_is_140(self):
        total = sum(amount for _, amount in SEASON_PRIZES)
        total += sum(amount for _, _, _, amount in PRIZE_WINDOWS)
        self.assertEqual(total, 140)

    def test_cumulative_points(self):
        scores = scores_by_gameweek(self.matches)
        self.assertEqual(cumulative_points(1, scores, 3, 4), 80)
        self.assertEqual(cumulative_points(2, scores, 3, 4), 80)

    def test_window_tie_uses_h2h_standings(self):
        scores = scores_by_gameweek(self.matches)
        standings = simulated_standings(self.managers, self.matches, 4)
        ranking = window_ranking(self.managers, scores, 3, 4, standings)
        self.assertEqual(ranking[0][0].manager_name, "Alice")
        self.assertEqual(ranking[0][1], 80)
        self.assertEqual(ranking[0][2], 1)

    def test_prizes_stack(self):
        awards, totals = payout_snapshot(
            self.managers,
            self.matches,
            report_gw=4,
            finalized_gw=4,
            preview_live=False,
        )
        self.assertEqual(sum(item["amount"] for item in awards), 140)
        self.assertEqual(totals[1]["projected"], 85)
        self.assertEqual(totals[2]["projected"], 25)

    def test_announcement_is_deterministic(self):
        first = build_announcement(
            "Test League", 4, self.managers, self.matches, 4, False
        )
        second = build_announcement(
            "Test League", 4, self.managers, self.matches, 4, False
        )
        self.assertEqual(first, second)
        self.assertIn("GW4 FINAL", first)
        self.assertIn("Current prize picture", first)

    def test_column_names(self):
        self.assertEqual(column_name(1), "A")
        self.assertEqual(column_name(26), "Z")
        self.assertEqual(column_name(27), "AA")


if __name__ == "__main__":
    unittest.main()
