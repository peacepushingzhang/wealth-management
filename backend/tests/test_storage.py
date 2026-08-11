import os
import tempfile
import unittest
from pathlib import Path

from backend.wealthpilot_api.storage import (
    load_workspace,
    save_index_purchase,
    save_manual_index_valuation,
    save_personal_workspace,
)


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["WEALTHPILOT_DB_PATH"] = str(Path(self.temp_dir.name) / "test.sqlite3")

    def tearDown(self) -> None:
        os.environ.pop("WEALTHPILOT_DB_PATH", None)
        self.temp_dir.cleanup()

    def test_seed_and_personal_workspace_round_trip(self) -> None:
        workspace = load_workspace()
        self.assertEqual(workspace["monthRecord"]["city"], "")
        self.assertEqual(len(workspace["assets"]), 6)
        self.assertEqual(len(workspace["indices"]), 10)
        workspace["monthRecord"]["salary"] = 12345
        workspace["assets"][0]["value"] = 23456
        save_personal_workspace(workspace)
        stored = load_workspace()
        self.assertEqual(stored["monthRecord"]["salary"], 12345)
        self.assertEqual(stored["assets"][0]["value"], 23456)

    def test_manual_valuation_and_purchase_are_persisted(self) -> None:
        save_manual_index_valuation(
            "SPX", pe_percentile=42.5, as_of="2026-08-11", source_url="https://example.com/spx"
        )
        purchase = save_index_purchase({
            "purchaseDate": "2026-08-11",
            "indexCode": "SPX",
            "fundCode": "513500",
            "fundName": "标普500ETF",
            "venue": "场内",
            "shares": 100,
            "amount": 1234.5,
        })
        workspace = load_workspace()
        spx = next(item for item in workspace["indices"] if item["code"] == "SPX")
        self.assertEqual(spx["pePercentile"], 42.5)
        self.assertEqual(workspace["purchases"][0]["id"], purchase["id"])
        self.assertEqual(workspace["purchases"][0]["shares"], 100)


if __name__ == "__main__":
    unittest.main()
