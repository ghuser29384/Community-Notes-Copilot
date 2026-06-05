from __future__ import annotations

import unittest

from app.services.costs import CostLedger
from app.settings import Settings
from app.x_client.community_notes import FixtureXCommunityNotesClient, LiveXCommunityNotesClient


class XClientTests(unittest.TestCase):
    def test_fixture_returns_eligible_posts_with_suggestions(self) -> None:
        settings = Settings()
        client = FixtureXCommunityNotesClient(settings, CostLedger(settings))
        response = client.search_posts_eligible_for_notes(test_mode=True, max_results=2)
        self.assertEqual(len(response["posts"]), 2)
        self.assertIn("suggested_source_links_with_counts", response["posts"][0])
        self.assertIn("note_request_suggestions", response["posts"][0])

    def test_live_x_api_disabled_by_default(self) -> None:
        settings = Settings()
        client = LiveXCommunityNotesClient(settings, CostLedger(settings))
        with self.assertRaises(PermissionError):
            client.search_posts_eligible_for_notes(test_mode=True, max_results=1)

    def test_non_test_fixture_write_disabled_by_default(self) -> None:
        settings = Settings()
        client = FixtureXCommunityNotesClient(settings, CostLedger(settings))
        with self.assertRaises(PermissionError):
            client.write_note("191", "note text", test_mode=False)

    def test_usage_api_snapshot_reconciles_with_local_ledger(self) -> None:
        settings = Settings()
        ledger = CostLedger(settings)
        client = FixtureXCommunityNotesClient(settings, ledger)
        client.search_posts_eligible_for_notes(test_mode=True, max_results=1)
        ledger.reconcile_usage_api(client.get_usage()["usage_api"])
        summary = ledger.summary()
        self.assertTrue(summary.usage_api_reconciled)
        self.assertEqual(summary.usage_api_daily_post_count, 1)
        self.assertTrue(summary.deduplication_soft_guarantee)


if __name__ == "__main__":
    unittest.main()
