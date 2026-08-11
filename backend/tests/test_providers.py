import unittest

from backend.wealthpilot_api.providers import (
    AkshareProvider,
    _extract_ifind_nav_points,
    _extract_ifind_valuation_points,
    _fund_candidate_score,
    _legulegu_points,
)


class _Frame:
    def __init__(self, records):
        self.records = records

    def to_dict(self, orient):
        if orient != "records":
            raise AssertionError("unexpected orient")
        return self.records


class _FakeAkshare:
    def stock_index_pe_lg(self, symbol):
        self.index_name = symbol
        return _Frame([
            {"日期": "2026-08-08", "滚动市盈率": 10.0},
            {"日期": "2026-08-11", "滚动市盈率": 10.5},
        ])

    def stock_index_pb_lg(self, symbol):
        return _Frame([
            {"日期": "2026-08-08", "市净率": 1.1},
            {"日期": "2026-08-11", "市净率": 1.2},
        ])

    def stock_zh_index_value_csindex(self, symbol):
        self.csindex_symbol = symbol
        return _Frame([{"日期": "2026-08-11", "市盈率1": 10.7, "市盈率2": 11.9}])

    def fund_etf_spot_em(self):
        return _Frame([
            {"代码": "510300", "名称": "沪深300ETF", "总市值": 120_000_000_000, "数据日期": "2026-08-11"},
            {"代码": "561990", "名称": "沪深300增强ETF", "总市值": 1_000_000_000, "数据日期": "2026-08-11"},
        ])

    def fund_name_em(self):
        return _Frame([
            {"基金代码": "000051", "基金简称": "华夏沪深300ETF联接A", "日期": "2026-08-11"},
            {"基金代码": "005658", "基金简称": "华夏沪深300ETF联接C", "日期": "2026-08-11"},
        ])


class _FakeAkshareWithoutPb(_FakeAkshare):
    def stock_index_pb_lg(self, symbol):
        raise AttributeError("upstream page changed")


class _FakeDowJonesAkshare(_FakeAkshare):
    def fund_etf_spot_em(self):
        return _Frame([
            {"代码": "513400", "名称": "道琼斯ETF鹏华", "总市值": 3_400_000_000},
        ])

    def fund_name_em(self):
        return _Frame([
            {"基金代码": "006679", "基金简称": "广发道琼斯石油指数A"},
            {"基金代码": "160140", "基金简称": "南方道琼斯美国精选A"},
            {"基金代码": "180003", "基金简称": "银华-道琼斯88指数"},
        ])


class ProviderParsingTests(unittest.TestCase):
    def test_extracts_ifind_date_sequence_tables(self) -> None:
        payload = {
            "errorcode": 0,
            "tables": [
                {
                    "thscode": "000300.SH",
                    "time": ["2026-08-07", "2026-08-08"],
                    "table": {
                        "configured_pe": [11.2, 11.5],
                        "configured_pb": [1.21, 1.24],
                    },
                }
            ],
        }
        points = _extract_ifind_valuation_points(payload, "configured_pe", "configured_pb")
        self.assertEqual([point.as_of for point in points], ["2026-08-07", "2026-08-08"])
        self.assertEqual(points[-1].pe, 11.5)
        self.assertEqual(points[-1].pb, 1.24)

    def test_ignores_invalid_ifind_nav_values(self) -> None:
        payload = {
            "tables": [
                {
                    "time": ["20260807", "20260808", "bad"],
                    "table": {"configured_nav": [1.01, None, 1.03]},
                }
            ]
        }
        points = _extract_ifind_nav_points(payload, "configured_nav")
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].as_of, "2026-08-07")

    def test_merges_legulegu_pe_and_pb_by_date(self) -> None:
        points = _legulegu_points(
            [{"日期": "2026-08-11", "滚动市盈率": 10.5}],
            [{"日期": "2026-08-11", "市净率": 1.2}],
        )
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].pe, 10.5)
        self.assertEqual(points[0].pb, 1.2)

    def test_akshare_index_uses_history_and_csindex_crosscheck(self) -> None:
        module = _FakeAkshare()
        series = AkshareProvider(module=module).fetch_index_valuations("000300.SH")
        self.assertEqual(module.index_name, "沪深300")
        self.assertEqual(module.csindex_symbol, "000300")
        self.assertEqual(series.points[-1].pb, 1.2)
        self.assertIn("中证官网", series.verification_message)

    def test_akshare_index_keeps_pe_when_optional_pb_is_unavailable(self) -> None:
        series = AkshareProvider(module=_FakeAkshareWithoutPb()).fetch_index_valuations("000300.SH")
        self.assertIsNone(series.points[-1].pb)
        self.assertIn("PB 暂不可用", series.verification_message)

    def test_bond_candidate_filter_rejects_convertible_and_mixed_funds(self) -> None:
        self.assertIsNotNone(_fund_candidate_score("示例中短债A"))
        self.assertIsNone(_fund_candidate_score("示例可转债增强A"))
        self.assertIsNone(_fund_candidate_score("示例混合债券A"))
        self.assertIsNone(_fund_candidate_score("示例30天滚动持有短债A"))

    def test_discovers_real_exchange_and_off_exchange_index_candidates(self) -> None:
        products = AkshareProvider(module=_FakeAkshare()).discover_index_fund_products(
            "000300.SH", "沪深300", 2
        )
        self.assertEqual([item.venue for item in products], ["场内", "场外"])
        self.assertEqual(products[0].code, "510300")
        self.assertEqual(products[0].scale_billion, 1200.0)
        self.assertEqual(products[1].code, "000051")

    def test_dow_jones_discovery_rejects_similarly_named_sector_products(self) -> None:
        products = AkshareProvider(module=_FakeDowJonesAkshare()).discover_index_fund_products(
            "DJI", "道琼斯工业指数", 2
        )
        self.assertEqual([item.code for item in products], ["513400"])


if __name__ == "__main__":
    unittest.main()
