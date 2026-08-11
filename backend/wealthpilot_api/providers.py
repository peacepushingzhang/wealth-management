from __future__ import annotations

import importlib
import json
import math
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple


IFIND_BASE_URL = "https://quantapi.51ifind.com/api/v1"
IFIND_DOC_URL = "https://quantapi.51ifind.com/gwstatic/static/ds_web/quantapi-web/help-center/manual.html"
AKSHARE_INDEX_DOC = "https://akshare.akfamily.xyz/data/index/index.html"
AKSHARE_FUND_DOC = "https://akshare.akfamily.xyz/data/fund/fund_public.html"
LEGULEGU_INDEX_SOURCE = "https://legulegu.com/stockdata/sz50-ttm-lyr"

LEGULEGU_INDEX_NAMES = {
    "000300.SH": "沪深300",
    "000905.SH": "中证500",
    "000852.SH": "中证1000",
}

INDEX_FUND_KEYWORDS = {
    "000300.SH": ("沪深300",),
    "000510.CSI": ("中证A500", "A500"),
    "000905.SH": ("中证500",),
    "000852.SH": ("中证1000",),
    "399006.SZ": ("创业板",),
    "000688.SH": ("科创50",),
    "SPX": ("标普500", "标普 500"),
    "NDX": ("纳斯达克100", "纳指100", "纳斯达克 100"),
    "DJI": ("道琼斯",),
    "RUT": ("罗素2000", "罗素 2000"),
}

INDEX_FUND_EXCLUDED_KEYWORDS = {
    "399006.SZ": ("创业板50",),
    "DJI": ("石油", "美国精选", "道琼斯88"),
}

BOND_FUND_PREFERRED_KEYWORDS = ("短债", "中短债", "政策性金融债", "政金债", "纯债")
BOND_FUND_EXCLUDED_KEYWORDS = (
    "可转债",
    "转债",
    "增强",
    "混合",
    "二级",
    "偏债",
    "定开",
    "持有",
)


class ProviderUnavailable(RuntimeError):
    """The provider cannot run because credentials, indicators, or packages are missing."""


class ProviderDataError(RuntimeError):
    """The provider responded, but the response is unusable."""


@dataclass(frozen=True)
class ValuationPoint:
    as_of: str
    pe: float
    pb: Optional[float] = None


@dataclass(frozen=True)
class IndexValuationSeries:
    code: str
    points: List[ValuationPoint]
    provider: str
    source_url: str
    verification_message: str = ""


@dataclass(frozen=True)
class FundNavPoint:
    as_of: str
    nav: float


@dataclass(frozen=True)
class BondFundSeries:
    code: str
    name: str
    issuer: str
    points: List[FundNavPoint]
    provider: str
    source_url: str
    verification_status: str


@dataclass(frozen=True)
class FundProductSnapshot:
    code: str
    name: str
    index_code: str
    venue: str
    scale_billion: Optional[float]
    tracking_error: Optional[float]
    total_fee: Optional[float]
    as_of: str
    provider: str
    source_url: str


class MarketDataProvider(Protocol):
    name: str

    def fetch_index_valuations(self, code: str) -> IndexValuationSeries:
        ...

    def fetch_bond_fund_nav(self, code: str) -> BondFundSeries:
        ...

    def discover_bond_fund_codes(self, limit: int) -> List[str]:
        ...

    def discover_index_fund_products(
        self, index_code: str, index_name: str, limit: int
    ) -> List[FundProductSnapshot]:
        ...


def _finite_positive(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _date_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().split(" ", 1)[0]
    if len(text) == 8 and text.isdigit():
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) >= 10 and text[4] in {"-", "/"}:
        return text[0:10].replace("/", "-")
    return None


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _extract_ifind_valuation_points(
    payload: Dict[str, Any], pe_indicator: str, pb_indicator: Optional[str]
) -> List[ValuationPoint]:
    body = payload.get("data") if isinstance(payload.get("data"), dict) and "tables" in payload["data"] else payload
    tables = body.get("tables") if isinstance(body, dict) else None
    if not isinstance(tables, list):
        raise ProviderDataError("iFinD 响应缺少 tables。")
    collected: Dict[str, ValuationPoint] = {}
    for block in tables:
        if not isinstance(block, dict):
            continue
        times = _as_list(block.get("time"))
        table = block.get("table") if isinstance(block.get("table"), dict) else {}
        pe_values = _as_list(table.get(pe_indicator))
        pb_values = _as_list(table.get(pb_indicator)) if pb_indicator else []
        for index, raw_time in enumerate(times):
            as_of = _date_iso(raw_time)
            pe = _finite_positive(pe_values[index] if index < len(pe_values) else None)
            pb = _finite_positive(pb_values[index] if index < len(pb_values) else None)
            if as_of and pe is not None:
                collected[as_of] = ValuationPoint(as_of=as_of, pe=pe, pb=pb)
    return sorted(collected.values(), key=lambda item: item.as_of)


def _extract_ifind_nav_points(payload: Dict[str, Any], indicator: str) -> List[FundNavPoint]:
    body = payload.get("data") if isinstance(payload.get("data"), dict) and "tables" in payload["data"] else payload
    tables = body.get("tables") if isinstance(body, dict) else None
    if not isinstance(tables, list):
        raise ProviderDataError("iFinD 响应缺少 tables。")
    collected: Dict[str, FundNavPoint] = {}
    for block in tables:
        if not isinstance(block, dict):
            continue
        times = _as_list(block.get("time"))
        table = block.get("table") if isinstance(block.get("table"), dict) else {}
        nav_values = _as_list(table.get(indicator))
        for index, raw_time in enumerate(times):
            as_of = _date_iso(raw_time)
            nav = _finite_positive(nav_values[index] if index < len(nav_values) else None)
            if as_of and nav is not None:
                collected[as_of] = FundNavPoint(as_of=as_of, nav=nav)
    return sorted(collected.values(), key=lambda item: item.as_of)


def _json_post(url: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else b"{}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30, context=ssl.create_default_context()) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ProviderDataError(f"数据源 HTTP {exc.code}。") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ProviderDataError("数据源网络请求或 JSON 解析失败。") from exc
    if not isinstance(result, dict):
        raise ProviderDataError("数据源返回格式不是 JSON 对象。")
    return result


def _metadata_for(code: str) -> Dict[str, str]:
    raw = os.getenv("WEALTHPILOT_BOND_FUND_METADATA_JSON", "").strip()
    if not raw:
        return {}
    try:
        configured = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderUnavailable("WEALTHPILOT_BOND_FUND_METADATA_JSON 不是有效 JSON。") from exc
    if not isinstance(configured, dict):
        raise ProviderUnavailable("WEALTHPILOT_BOND_FUND_METADATA_JSON 必须是对象。")
    value = configured.get(code) or configured.get(code.split(".", 1)[0]) or {}
    return value if isinstance(value, dict) else {}


def _legulegu_points(
    pe_records: Iterable[Dict[str, Any]], pb_records: Iterable[Dict[str, Any]]
) -> List[ValuationPoint]:
    pb_by_date: Dict[str, float] = {}
    for row in pb_records:
        as_of = _date_iso(row.get("日期"))
        pb = _finite_positive(row.get("市净率")) or _finite_positive(row.get("等权市净率"))
        if as_of and pb is not None:
            pb_by_date[as_of] = pb

    collected: Dict[str, ValuationPoint] = {}
    for row in pe_records:
        as_of = _date_iso(row.get("日期"))
        pe = _finite_positive(row.get("滚动市盈率")) or _finite_positive(row.get("等权滚动市盈率"))
        if as_of and pe is not None:
            collected[as_of] = ValuationPoint(as_of=as_of, pe=pe, pb=pb_by_date.get(as_of))
    return sorted(collected.values(), key=lambda item: item.as_of)


def _csindex_latest(frame: Any) -> Tuple[str, List[float]]:
    candidates: List[Tuple[str, List[float]]] = []
    for row in frame.to_dict("records"):
        as_of = _date_iso(row.get("日期"))
        pe_values = [
            value
            for value in (
                _finite_positive(row.get("市盈率1")),
                _finite_positive(row.get("市盈率2")),
            )
            if value is not None
        ]
        if as_of and pe_values:
            candidates.append((as_of, pe_values))
    if not candidates:
        raise ProviderDataError("中证指数官网没有可用于校验的最新 PE。")
    return max(candidates, key=lambda item: item[0])


def _fund_candidate_score(name: str) -> Optional[Tuple[int, str]]:
    if any(keyword in name for keyword in BOND_FUND_EXCLUDED_KEYWORDS):
        return None
    for rank, keyword in enumerate(BOND_FUND_PREFERRED_KEYWORDS):
        if keyword in name:
            return rank, name
    return None


class IFindProvider:
    name = "ifind"

    def __init__(self) -> None:
        self._cached_access_token: Optional[str] = None

    def _access_token(self) -> str:
        configured = os.getenv("IFIND_ACCESS_TOKEN", "").strip()
        if configured:
            return configured
        if self._cached_access_token:
            return self._cached_access_token
        refresh_token = os.getenv("IFIND_REFRESH_TOKEN", "").strip()
        if not refresh_token:
            raise ProviderUnavailable("缺少 IFIND_REFRESH_TOKEN 或 IFIND_ACCESS_TOKEN。")
        result = _json_post(
            f"{IFIND_BASE_URL}/get_access_token",
            {"Content-Type": "application/json", "refresh_token": refresh_token},
        )
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        token = str(data.get("access_token") or "").strip()
        if not token:
            raise ProviderDataError("iFinD 未返回 access_token。")
        self._cached_access_token = token
        return token

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = _json_post(
            f"{IFIND_BASE_URL}/{endpoint}",
            {"Content-Type": "application/json", "access_token": self._access_token(), "ifindlang": "cn"},
            payload,
        )
        error_code = result.get("errorcode")
        if error_code not in (None, 0, "0"):
            raise ProviderDataError(f"iFinD 返回错误 {error_code}: {result.get('errmsg') or '未知错误'}")
        return result

    @staticmethod
    def _provider_code(code: str) -> str:
        aliases = {"000510.CSI": "000510.SH"}
        raw = os.getenv("IFIND_CODE_MAP_JSON", "").strip()
        if raw:
            try:
                custom = json.loads(raw)
                if isinstance(custom, dict):
                    aliases.update({str(key): str(value) for key, value in custom.items()})
            except json.JSONDecodeError as exc:
                raise ProviderUnavailable("IFIND_CODE_MAP_JSON 不是有效 JSON。") from exc
        return aliases.get(code, code)

    @staticmethod
    def _indicator(name: str, required: bool = True) -> Optional[Dict[str, Any]]:
        indicator = os.getenv(name, "").strip()
        if not indicator:
            if required:
                raise ProviderUnavailable(f"缺少 {name}，请从 iFinD 超级命令复制指标名。")
            return None
        params_raw = os.getenv(f"{name}_PARAMS", "").strip()
        params = [item.strip() for item in params_raw.split(",")] if params_raw else []
        result: Dict[str, Any] = {"indicator": indicator}
        if params:
            result["indiparams"] = params
        return result

    def _date_sequence(
        self, code: str, start: date, end: date, indicators: Iterable[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        cursor = start
        while cursor <= end:
            chunk_end = min(end, cursor + timedelta(days=364))
            results.append(
                self._post(
                    "date_sequence",
                    {
                        "codes": self._provider_code(code),
                        "startdate": cursor.strftime("%Y%m%d"),
                        "enddate": chunk_end.strftime("%Y%m%d"),
                        "functionpara": {"Fill": "Blank", "Interval": "D"},
                        "indipara": list(indicators),
                    },
                )
            )
            cursor = chunk_end + timedelta(days=1)
        return results

    def fetch_index_valuations(self, code: str) -> IndexValuationSeries:
        pe_config = self._indicator("IFIND_INDEX_PE_INDICATOR")
        pb_config = self._indicator("IFIND_INDEX_PB_INDICATOR", required=False)
        assert pe_config is not None
        end = date.today()
        start = end - timedelta(days=365 * 5)
        payloads = self._date_sequence(code, start, end, [item for item in (pe_config, pb_config) if item])
        points: Dict[str, ValuationPoint] = {}
        for payload in payloads:
            for point in _extract_ifind_valuation_points(
                payload, pe_config["indicator"], pb_config["indicator"] if pb_config else None
            ):
                points[point.as_of] = point
        if not points:
            raise ProviderDataError(f"iFinD 未返回 {code} 的有效 PE 数据。")
        return IndexValuationSeries(code, sorted(points.values(), key=lambda item: item.as_of), self.name, IFIND_DOC_URL)

    def fetch_bond_fund_nav(self, code: str) -> BondFundSeries:
        nav_config = self._indicator("IFIND_FUND_NAV_INDICATOR")
        assert nav_config is not None
        end = date.today()
        start = end - timedelta(days=430)
        payloads = self._date_sequence(code, start, end, [nav_config])
        points: Dict[str, FundNavPoint] = {}
        for payload in payloads:
            for point in _extract_ifind_nav_points(payload, nav_config["indicator"]):
                points[point.as_of] = point
        if not points:
            raise ProviderDataError(f"iFinD 未返回 {code} 的有效净值。")
        metadata = _metadata_for(code)
        return BondFundSeries(
            code=code,
            name=metadata.get("name", f"债券基金 {code}"),
            issuer=metadata.get("issuer", "待基金公司官网核验"),
            points=sorted(points.values(), key=lambda item: item.as_of),
            provider=self.name,
            source_url=metadata.get("source_url", IFIND_DOC_URL),
            verification_status="official_metadata" if metadata.get("source_url") else "market_data_only",
        )


class AkshareProvider:
    name = "akshare"

    def __init__(self, module: Optional[Any] = None) -> None:
        self._fund_catalog: Optional[Dict[str, str]] = None
        self._etf_product_records: Optional[List[Dict[str, Any]]] = None
        self._open_index_product_records: Optional[List[Dict[str, Any]]] = None
        self._akshare = module

    def _module(self) -> Any:
        if self._akshare is not None:
            return self._akshare
        try:
            self._akshare = importlib.import_module("akshare")
            return self._akshare
        except ImportError as exc:
            raise ProviderUnavailable("未安装 AKShare；请执行 pip install -r requirements.txt。") from exc

    @staticmethod
    def _retry(operation: Any, label: str) -> Any:
        attempts = max(1, min(3, int(os.getenv("WEALTHPILOT_PROVIDER_ATTEMPTS", "2"))))
        last_error: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                return operation()
            except Exception as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(1)
        assert last_error is not None
        raise ProviderDataError(f"{label} 连续 {attempts} 次请求失败：{last_error}") from last_error

    def fetch_index_valuations(self, code: str) -> IndexValuationSeries:
        index_name = LEGULEGU_INDEX_NAMES.get(code)
        if not index_name:
            raise ProviderUnavailable(
                f"免费历史估值源暂不覆盖 {code}；不使用短样本或近似指数替代。"
            )
        module = self._module()
        pe_frame = self._retry(
            lambda: module.stock_index_pe_lg(symbol=index_name), f"{index_name} 乐咕 PE"
        )
        pb_records: List[Dict[str, Any]] = []
        pb_message = ""
        try:
            pb_frame = self._retry(
                lambda: module.stock_index_pb_lg(symbol=index_name), f"{index_name} 乐咕 PB"
            )
            pb_records = pb_frame.to_dict("records")
        except Exception as exc:
            pb_message = f" PB 暂不可用（{type(exc).__name__}），本次仅生成 PE 百分位。"
        points = _legulegu_points(pe_frame.to_dict("records"), pb_records)
        if not points:
            raise ProviderDataError(f"AKShare/乐咕未返回 {code} 的历史 PE 数据。")

        symbol = code.split(".", 1)[0]
        check_frame = self._retry(
            lambda: module.stock_zh_index_value_csindex(symbol=symbol), f"{index_name} 中证 PE 校验"
        )
        check_as_of, check_values = _csindex_latest(check_frame)
        current = points[-1]
        max_age_days = int(os.getenv("WEALTHPILOT_INDEX_CROSSCHECK_MAX_AGE_DAYS", "5"))
        if abs((date.fromisoformat(current.as_of) - date.fromisoformat(check_as_of)).days) > max_age_days:
            raise ProviderDataError(
                f"乐咕最新日期 {current.as_of} 与中证校验日期 {check_as_of} 相差超过 {max_age_days} 天。"
            )
        closest = min(check_values, key=lambda value: abs(value - current.pe))
        discrepancy = abs(closest / current.pe - 1) * 100
        # Legulegu exposes aggregate TTM PE while CSIndex publishes two official PE
        # definitions. They are suitable for a broad sanity check, not exact equality.
        max_discrepancy = float(os.getenv("WEALTHPILOT_INDEX_MAX_PE_DISCREPANCY", "15"))
        if discrepancy > max_discrepancy:
            raise ProviderDataError(
                f"乐咕 PE {current.pe:.4g} 与中证官网 PE {closest:.4g} 相差 {discrepancy:.2f}%，"
                f"超过 {max_discrepancy:.2f}% 门槛。"
            )
        verification_message = (
            f"历史数据来自乐咕；中证官网 {check_as_of} PE={closest:.4g}，"
            f"与历史口径最新值相差 {discrepancy:.2f}%。{pb_message}"
        )
        return IndexValuationSeries(
            code,
            points,
            self.name,
            LEGULEGU_INDEX_SOURCE,
            verification_message,
        )

    def discover_bond_fund_codes(self, limit: int) -> List[str]:
        frame = self._retry(lambda: self._module().fund_name_em(), "东方财富基金目录")
        candidates: List[Tuple[int, str, str]] = []
        for row in frame.to_dict("records"):
            code = str(row.get("基金代码") or "").strip()
            name = str(row.get("基金简称") or "").strip()
            fund_type = str(row.get("基金类型") or "").strip()
            if not code or "债券" not in fund_type:
                continue
            score = _fund_candidate_score(name)
            if score is not None:
                candidates.append((score[0], score[1], code))
        candidates.sort()
        selected: List[str] = []
        seen_base_names = set()
        for _, name, code in candidates:
            base_name = re.sub(r"(?:A|B|C|D|E|I|Y|人民币|美元)$", "", name, flags=re.IGNORECASE)
            if base_name in seen_base_names:
                continue
            seen_base_names.add(base_name)
            selected.append(f"{code}.OF")
            if len(selected) >= limit:
                break
        if not selected:
            raise ProviderDataError("东方财富基金目录中没有符合稳健筛选规则的债券基金。")
        return selected

    def _load_etf_product_records(self) -> List[Dict[str, Any]]:
        if self._etf_product_records is None:
            frame = self._retry(lambda: self._module().fund_etf_spot_em(), "东方财富 ETF 行情")
            self._etf_product_records = frame.to_dict("records")
        return self._etf_product_records

    def _load_open_index_product_records(self) -> List[Dict[str, Any]]:
        if self._open_index_product_records is None:
            frame = self._retry(lambda: self._module().fund_name_em(), "东方财富完整基金目录")
            self._open_index_product_records = frame.to_dict("records")
        return self._open_index_product_records

    def discover_index_fund_products(
        self, index_code: str, index_name: str, limit: int = 2
    ) -> List[FundProductSnapshot]:
        keywords = INDEX_FUND_KEYWORDS.get(index_code, (index_name,))
        today = date.today().isoformat()

        def matches(name: str) -> bool:
            compact = re.sub(r"\s+", "", name.upper())
            excluded = INDEX_FUND_EXCLUDED_KEYWORDS.get(index_code, ())
            return (
                not any(word in name for word in ("增强", "量化", "杠杆"))
                and not any(re.sub(r"\s+", "", word.upper()) in compact for word in excluded)
                and any(re.sub(r"\s+", "", word.upper()) in compact for word in keywords)
            )

        exchange: List[FundProductSnapshot] = []
        for row in self._load_etf_product_records():
            code = str(row.get("代码") or "").strip()
            name = str(row.get("名称") or "").strip()
            if not code or not matches(name):
                continue
            market_value = _finite_positive(row.get("总市值"))
            exchange.append(FundProductSnapshot(
                code=code,
                name=name,
                index_code=index_code,
                venue="场内",
                scale_billion=round(market_value / 100_000_000, 2) if market_value else None,
                tracking_error=None,
                total_fee=None,
                as_of=_date_iso(row.get("数据日期")) or today,
                provider=self.name,
                source_url=f"https://quote.eastmoney.com/{'sh' if code.startswith(('5', '6')) else 'sz'}{code}.html",
            ))
        exchange.sort(key=lambda item: (-(item.scale_billion or 0), item.code))

        off_exchange: List[FundProductSnapshot] = []
        exchange_codes = {item.code for item in exchange}
        seen_names = set()
        for row in self._load_open_index_product_records():
            code = str(row.get("基金代码") or "").strip()
            name = str(row.get("基金简称") or "").strip()
            if not code or code in exchange_codes or not matches(name):
                continue
            base_name = re.sub(r"(?:A|C|E|I|Y)$", "", name, flags=re.IGNORECASE)
            if base_name in seen_names:
                continue
            seen_names.add(base_name)
            off_exchange.append(FundProductSnapshot(
                code=code,
                name=name,
                index_code=index_code,
                venue="场外",
                scale_billion=None,
                tracking_error=None,
                total_fee=None,
                as_of=today,
                provider=self.name,
                source_url=f"https://fund.eastmoney.com/{code}.html",
            ))
        off_exchange.sort(key=lambda item: (0 if item.name.upper().endswith("A") else 1, item.code))
        return exchange[:limit] + off_exchange[:limit]

    def _load_fund_catalog(self) -> Dict[str, str]:
        if self._fund_catalog is not None:
            return self._fund_catalog
        frame = self._retry(
            lambda: self._module().fund_open_fund_daily_em(), "东方财富开放式基金目录"
        )
        catalog: Dict[str, str] = {}
        for row in frame.to_dict("records"):
            code = str(row.get("基金代码") or "").strip()
            name = str(row.get("基金简称") or "").strip()
            if code:
                catalog[code] = name
        self._fund_catalog = catalog
        return catalog

    def fetch_bond_fund_nav(self, code: str) -> BondFundSeries:
        bare_code = code.split(".", 1)[0]
        frame = self._retry(
            lambda: self._module().fund_open_fund_info_em(
                symbol=bare_code, indicator="单位净值走势"
            ),
            f"基金 {bare_code} 净值",
        )
        points: List[FundNavPoint] = []
        for row in frame.to_dict("records"):
            as_of = _date_iso(row.get("净值日期"))
            nav = _finite_positive(row.get("单位净值"))
            if as_of and nav is not None:
                points.append(FundNavPoint(as_of=as_of, nav=nav))
        points.sort(key=lambda item: item.as_of)
        if not points:
            raise ProviderDataError(f"AKShare 未返回 {bare_code} 的基金净值。")
        metadata = _metadata_for(code)
        issuer = metadata.get("issuer")
        if not issuer:
            try:
                overview = self._retry(
                    lambda: self._module().fund_overview_em(symbol=bare_code),
                    f"基金 {bare_code} 概况",
                )
                overview_records = overview.to_dict("records")
                if overview_records:
                    issuer = str(overview_records[0].get("基金管理人") or "").strip() or None
            except Exception:
                issuer = None
        name = metadata.get("name") or self._load_fund_catalog().get(bare_code) or f"债券基金 {bare_code}"
        source = metadata.get("source_url") or f"https://fund.eastmoney.com/{bare_code}.html"
        return BondFundSeries(
            code=code,
            name=name,
            issuer=issuer or "待基金公司官网核验",
            points=points,
            provider=self.name,
            source_url=source,
            verification_status="official_metadata" if metadata.get("source_url") else "market_data_only",
        )


def configured_providers(dataset: str) -> List[MarketDataProvider]:
    env_name = "WEALTHPILOT_INDEX_PROVIDERS" if dataset == "indices" else "WEALTHPILOT_FUND_PROVIDERS"
    names = [item.strip().lower() for item in os.getenv(env_name, "akshare").split(",") if item.strip()]
    factories = {"ifind": IFindProvider, "akshare": AkshareProvider}
    unknown = [name for name in names if name not in factories]
    if unknown:
        raise ProviderUnavailable(f"{env_name} 包含未知供应商: {', '.join(unknown)}")
    if not names:
        raise ProviderUnavailable(f"{env_name} 不能为空。")
    return [factories[name]() for name in names]
