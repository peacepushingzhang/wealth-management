import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from backend.wealthpilot_api.collectors import sync_a_share_indices, sync_bond_funds, sync_index_fund_products
from backend.wealthpilot_api.providers import (
    BondFundSeries,
    FundProductSnapshot,
    FundNavPoint,
    IndexValuationSeries,
    ValuationPoint,
)
from backend.wealthpilot_api.storage import get_evidence, load_workspace


class FailingProvider:
    name = "primary"

    def fetch_index_valuations(self, code: str) -> IndexValuationSeries:
        raise RuntimeError("primary unavailable")

    def fetch_bond_fund_nav(self, code: str) -> BondFundSeries:
        raise RuntimeError("primary unavailable")


class WorkingProvider:
    name = "fallback"

    def fetch_index_valuations(self, code: str) -> IndexValuationSeries:
        start = date.today() - timedelta(days=39)
        points = [
            ValuationPoint((start + timedelta(days=index)).isoformat(), 10 + index / 10, 1 + index / 100)
            for index in range(40)
        ]
        return IndexValuationSeries(code, points, self.name, "https://example.com/index")

    def fetch_bond_fund_nav(self, code: str) -> BondFundSeries:
        start = date.today() - timedelta(days=219)
        points = [
            FundNavPoint((start + timedelta(days=index)).isoformat(), 1 + index / 10000)
            for index in range(220)
        ]
        return BondFundSeries(
            code,
            "测试短债基金",
            "测试基金公司",
            points,
            self.name,
            "https://example.com/fund",
            "official_metadata",
        )

    def discover_bond_fund_codes(self, limit: int):
        return ["000001.OF"][:limit]

    def discover_index_fund_products(self, index_code: str, index_name: str, limit: int):
        return [FundProductSnapshot(
            code=f"F{index_code.replace('.', '')}",
            name=f"{index_name}ETF",
            index_code=index_code,
            venue="场内",
            scale_billion=10,
            tracking_error=None,
            total_fee=None,
            as_of=date.today().isoformat(),
            provider=self.name,
            source_url="https://example.com/fund-product",
        )]


class CollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["WEALTHPILOT_DB_PATH"] = str(Path(self.temp_dir.name) / "test.sqlite3")
        os.environ["WEALTHPILOT_MIN_INDEX_SAMPLES"] = "30"
        os.environ["WEALTHPILOT_BOND_FUND_CODES"] = "000001.OF"

    def tearDown(self) -> None:
        for name in (
            "WEALTHPILOT_DB_PATH",
            "WEALTHPILOT_MIN_INDEX_SAMPLES",
            "WEALTHPILOT_BOND_FUND_CODES",
        ):
            os.environ.pop(name, None)
        self.temp_dir.cleanup()

    def test_index_sync_records_explicit_fallback(self) -> None:
        result = sync_a_share_indices([FailingProvider(), WorkingProvider()])
        self.assertEqual(result["updated"], 6)
        evidence = get_evidence("indices", "000300.SH")
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence["provider"], "fallback")
        self.assertEqual(evidence["fallback_used"], 1)
        workspace = load_workspace()
        index = next(item for item in workspace["indices"] if item["code"] == "000300.SH")
        self.assertIsNotNone(index["pePercentile"])
        self.assertTrue(index["evidence"]["fallbackUsed"])

    def test_bond_sync_calculates_metrics_and_evidence(self) -> None:
        result = sync_bond_funds([FailingProvider(), WorkingProvider()])
        self.assertEqual(result["updated"], 1)
        fund = load_workspace()["bondFunds"][0]
        self.assertEqual(fund["name"], "测试短债基金")
        self.assertIsNotNone(fund["oneYearReturn"])
        self.assertEqual(fund["evidence"]["provider"], "fallback")
        self.assertTrue(fund["evidence"]["fallbackUsed"])

    def test_bond_sync_discovers_candidates_without_manual_codes(self) -> None:
        os.environ.pop("WEALTHPILOT_BOND_FUND_CODES", None)
        result = sync_bond_funds([WorkingProvider()])
        self.assertEqual(result["updated"], 1)
        evidence = get_evidence("funds", "000001.OF")
        self.assertIn("自动发现", evidence["message"])

    def test_index_fund_sync_populates_candidates_without_fake_metrics(self) -> None:
        result = sync_index_fund_products([WorkingProvider()])
        self.assertEqual(result["coveredIndices"], 10)
        products = load_workspace()["fundProducts"]
        self.assertEqual(len(products), 10)
        self.assertIsNone(products[0]["trackingError"])
        self.assertEqual(products[0]["evidence"]["status"], "candidate_only")


if __name__ == "__main__":
    unittest.main()
