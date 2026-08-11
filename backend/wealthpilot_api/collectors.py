from __future__ import annotations

import hashlib
import json
import math
import os
import re
import ssl
import urllib.request
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .providers import (
    BondFundSeries,
    FundProductSnapshot,
    IndexValuationSeries,
    MarketDataProvider,
    ProviderDataError,
    configured_providers,
)
from .storage import (
    connection,
    get_evidence,
    initialize,
    now_iso,
    record_evidence,
    record_sync,
)


class SyncConfigurationError(RuntimeError):
    pass


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


def _normalized_content_hash(content: bytes, content_type: str) -> str:
    text = content.decode("utf-8", errors="ignore")
    if "html" in content_type.lower() or "<html" in text[:500].lower():
        parser = _VisibleTextParser()
        parser.feed(text)
        text = " ".join(parser.parts)
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _percentile(values: Iterable[float], current: float) -> float:
    usable = [
        float(value)
        for value in values
        if value is not None and math.isfinite(float(value)) and float(value) > 0
    ]
    if not usable:
        raise RuntimeError("历史估值样本为空")
    return round(sum(value <= current for value in usable) / len(usable) * 100, 2)


def _max_drawdown(values: List[float]) -> float:
    peak = 0.0
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value / peak - 1) * 100)
    return round(worst, 2)


def _freshness(as_of: Optional[str], max_age_days: int) -> str:
    if not as_of:
        return "missing"
    try:
        age = (date.today() - date.fromisoformat(as_of)).days
    except ValueError:
        return "invalid"
    return "fresh" if age <= max_age_days else "stale"


def _fetch_with_fallback(
    providers: List[MarketDataProvider], method: str, code: str
) -> Tuple[Any, bool, List[str]]:
    errors: List[str] = []
    for index, provider in enumerate(providers):
        try:
            return getattr(provider, method)(code), index > 0, errors
        except Exception as exc:
            errors.append(f"{provider.name}: {exc}")
    raise ProviderDataError("；".join(errors) or "没有可用数据供应商。")


def _block_index(code: str, message: str) -> None:
    with connection() as db:
        db.execute(
            """UPDATE index_valuations SET pe_percentile=NULL, pb_percentile=NULL,
               updated_at=? WHERE code=?""",
            (now_iso(), code),
        )
    existing = get_evidence("indices", code)
    record_evidence(
        dataset="indices",
        item_key=code,
        provider=(existing or {}).get("provider"),
        source_url=(existing or {}).get("source_url"),
        as_of=(existing or {}).get("as_of"),
        freshness="missing",
        fallback_used=bool((existing or {}).get("fallback_used")),
        status="blocked",
        message=message,
    )


def sync_a_share_indices(
    providers: Optional[List[MarketDataProvider]] = None,
) -> Dict[str, Any]:
    initialize()
    active_providers = providers or configured_providers("indices")
    min_samples = max(30, int(os.getenv("WEALTHPILOT_MIN_INDEX_SAMPLES", "250")))
    with connection() as db:
        codes = [row["code"] for row in db.execute("SELECT code FROM index_catalog WHERE market='A股'")]
    updated = 0
    latest_as_of: Optional[str] = None
    used_providers: List[str] = []
    failures: List[str] = []
    for code in codes:
        try:
            series, fallback_used, prior_errors = _fetch_with_fallback(
                active_providers, "fetch_index_valuations", code
            )
            assert isinstance(series, IndexValuationSeries)
            if len(series.points) < min_samples:
                raise ProviderDataError(
                    f"{series.provider} 只有 {len(series.points)} 个估值样本，低于 {min_samples} 个安全门槛。"
                )
            current = series.points[-1]
            current_freshness = _freshness(current.as_of, 4)
            if current_freshness != "fresh":
                raise ProviderDataError(
                    f"{series.provider} 最新估值截至 {current.as_of}，已过期，禁止生成定投结论。"
                )
            pe_percentile = _percentile((point.pe for point in series.points), current.pe)
            pb_points = [point.pb for point in series.points if point.pb is not None]
            pb_percentile = _percentile(pb_points, current.pb) if current.pb is not None and pb_points else None
            with connection() as db:
                db.execute(
                    """UPDATE index_valuations SET pe=?, pe_percentile=?, pb=?, pb_percentile=?,
                       as_of=?, source_url=?, updated_at=? WHERE code=?""",
                    (
                        current.pe,
                        pe_percentile,
                        current.pb,
                        pb_percentile,
                        current.as_of,
                        series.source_url,
                        now_iso(),
                        code,
                    ),
                )
            message = f"使用 {len(series.points)} 个样本计算 PE 百分位。"
            if series.verification_message:
                message += f" {series.verification_message}"
            if prior_errors:
                message += f" 前序供应商失败：{'；'.join(prior_errors)}"
            record_evidence(
                dataset="indices",
                item_key=code,
                provider=series.provider,
                source_url=series.source_url,
                as_of=current.as_of,
                freshness=current_freshness,
                fallback_used=fallback_used,
                status="verified",
                message=message,
            )
            latest_as_of = max(latest_as_of or current.as_of, current.as_of)
            used_providers.append(series.provider)
            updated += 1
        except Exception as exc:
            message = str(exc)
            failures.append(f"{code}: {message}")
            _block_index(code, message)
    if not updated:
        raise ProviderDataError("所有 A 股指数同步失败。" + (f" {failures[0]}" if failures else ""))
    status = "success" if updated == len(codes) else "partial"
    providers_text = ", ".join(dict.fromkeys(used_providers))
    record_sync(
        "indices",
        status,
        latest_as_of,
        f"{providers_text} 已更新 {updated}/{len(codes)} 个 A 股宽基；失败项不会生成定投结论。",
    )
    return {
        "dataset": "indices",
        "status": status,
        "updated": updated,
        "total": len(codes),
        "providers": list(dict.fromkeys(used_providers)),
        "asOf": latest_as_of,
        "failures": failures,
    }


def sync_bond_funds(
    providers: Optional[List[MarketDataProvider]] = None,
) -> Dict[str, Any]:
    initialize()
    active_providers = providers or configured_providers("funds")
    codes = [
        code.strip()
        for code in os.getenv("WEALTHPILOT_BOND_FUND_CODES", "").split(",")
        if code.strip()
    ]
    discovery_message = ""
    if not codes:
        discovery_errors: List[str] = []
        limit = max(1, min(20, int(os.getenv("WEALTHPILOT_BOND_FUND_LIMIT", "8"))))
        for provider in active_providers:
            discover = getattr(provider, "discover_bond_fund_codes", None)
            if not callable(discover):
                discovery_errors.append(f"{provider.name}: 不支持基金目录发现")
                continue
            try:
                codes = discover(limit)
                discovery_message = f"由 {provider.name} 自动发现 {len(codes)} 个稳健债基研究候选。"
                break
            except Exception as exc:
                discovery_errors.append(f"{provider.name}: {exc}")
        if not codes:
            raise SyncConfigurationError(
                "没有可用的债券基金候选。" + (f" {'；'.join(discovery_errors)}" if discovery_errors else "")
            )
    updated = 0
    latest_as_of: Optional[str] = None
    used_providers: List[str] = []
    successful_codes: List[str] = []
    failures: List[str] = []
    for code in codes:
        try:
            series, fallback_used, prior_errors = _fetch_with_fallback(
                active_providers, "fetch_bond_fund_nav", code
            )
            assert isinstance(series, BondFundSeries)
            if len(series.points) < 2:
                raise ProviderDataError("基金净值少于两个交易日。")
            points = series.points[-260:]
            navs = [point.nav for point in points]
            daily_change = (navs[-1] / navs[-2] - 1) * 100
            one_year_return = (navs[-1] / navs[0] - 1) * 100 if len(navs) > 200 else None
            as_of = points[-1].as_of
            with connection() as db:
                db.execute(
                    """INSERT INTO bond_fund_quotes
                    (code, name, issuer, daily_change, one_year_return, max_drawdown, nav, as_of, source_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET name=excluded.name, issuer=excluded.issuer,
                      daily_change=excluded.daily_change, one_year_return=excluded.one_year_return,
                      max_drawdown=excluded.max_drawdown, nav=excluded.nav, as_of=excluded.as_of,
                      source_url=excluded.source_url""",
                    (
                        code,
                        series.name,
                        series.issuer,
                        round(daily_change, 2),
                        round(one_year_return, 2) if one_year_return is not None else None,
                        _max_drawdown(navs),
                        navs[-1],
                        as_of,
                        series.source_url,
                    ),
                )
            message = f"{discovery_message} 使用 {len(points)} 个净值样本；{series.verification_status}。".strip()
            if prior_errors:
                message += f" 前序供应商失败：{'；'.join(prior_errors)}"
            record_evidence(
                dataset="funds",
                item_key=code,
                provider=series.provider,
                source_url=series.source_url,
                as_of=as_of,
                freshness=_freshness(as_of, 4),
                fallback_used=fallback_used,
                status=series.verification_status,
                message=message,
            )
            latest_as_of = max(latest_as_of or as_of, as_of)
            used_providers.append(series.provider)
            successful_codes.append(code)
            updated += 1
        except Exception as exc:
            failures.append(f"{code}: {exc}")
            existing = get_evidence("funds", code)
            record_evidence(
                dataset="funds",
                item_key=code,
                provider=(existing or {}).get("provider"),
                source_url=(existing or {}).get("source_url"),
                as_of=(existing or {}).get("as_of"),
                freshness="missing",
                fallback_used=bool((existing or {}).get("fallback_used")),
                status="blocked",
                message=str(exc),
            )
    if not updated:
        raise ProviderDataError("所有债券基金同步失败。" + (f" {failures[0]}" if failures else ""))
    placeholders = ",".join("?" for _ in successful_codes)
    with connection() as db:
        db.execute(
            f"DELETE FROM bond_fund_quotes WHERE code NOT IN ({placeholders})",
            successful_codes,
        )
        db.execute(
            f"DELETE FROM market_evidence WHERE dataset='funds' AND item_key NOT IN ({placeholders})",
            successful_codes,
        )
    status = "success" if updated == len(codes) else "partial"
    providers_text = ", ".join(dict.fromkeys(used_providers))
    record_sync(
        "funds",
        status,
        latest_as_of,
        f"{providers_text} 已更新 {updated}/{len(codes)} 个债券基金研究候选；基金公司资料仍需核验。",
    )
    return {
        "dataset": "funds",
        "status": status,
        "updated": updated,
        "total": len(codes),
        "providers": list(dict.fromkeys(used_providers)),
        "asOf": latest_as_of,
        "failures": failures,
    }


def sync_index_fund_products(
    providers: Optional[List[MarketDataProvider]] = None,
) -> Dict[str, Any]:
    initialize()
    active_providers = providers or configured_providers("funds")
    with connection() as db:
        indices = [dict(row) for row in db.execute("SELECT code, name FROM index_catalog ORDER BY rowid")]
    limit = max(1, min(4, int(os.getenv("WEALTHPILOT_INDEX_FUND_LIMIT", "2"))))
    snapshots: List[FundProductSnapshot] = []
    failures: List[str] = []
    covered_indices = 0
    for index in indices:
        found: List[FundProductSnapshot] = []
        errors: List[str] = []
        for provider in active_providers:
            discover = getattr(provider, "discover_index_fund_products", None)
            if not callable(discover):
                errors.append(f"{provider.name}: 不支持指数基金发现")
                continue
            try:
                found = discover(index["code"], index["name"], limit)
                if found:
                    break
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
        if not found:
            failures.append(f"{index['code']}: {'；'.join(errors) or '未发现匹配产品'}")
            continue
        covered_indices += 1
        snapshots.extend(found)

    if not snapshots:
        raise ProviderDataError("没有同步到任何宽基指数基金候选。")
    successful_codes = [item.code for item in snapshots]
    with connection() as db:
        for item in snapshots:
            db.execute(
                """INSERT INTO fund_products
                   (code, name, index_code, venue, scale_billion, tracking_error, total_fee, as_of, source_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(code) DO UPDATE SET name=excluded.name, index_code=excluded.index_code,
                     venue=excluded.venue, scale_billion=excluded.scale_billion,
                     tracking_error=excluded.tracking_error, total_fee=excluded.total_fee,
                     as_of=excluded.as_of, source_url=excluded.source_url""",
                (
                    item.code, item.name, item.index_code, item.venue, item.scale_billion,
                    item.tracking_error, item.total_fee, item.as_of, item.source_url,
                ),
            )
        placeholders = ",".join("?" for _ in successful_codes)
        db.execute(f"DELETE FROM fund_products WHERE code NOT IN ({placeholders})", successful_codes)

    for item in snapshots:
        missing = [
            label for value, label in (
                (item.scale_billion, "规模"),
                (item.tracking_error, "跟踪误差"),
                (item.total_fee, "年度费率"),
            ) if value is None
        ]
        record_evidence(
            dataset="fund_products",
            item_key=item.code,
            provider=item.provider,
            source_url=item.source_url,
            as_of=item.as_of,
            freshness=_freshness(item.as_of, 4),
            fallback_used=False,
            status="candidate_only" if missing else "verified",
            message=(
                f"东方财富公开目录自动发现；{'、'.join(missing)}仍需基金公司公告核验。"
                if missing else "规模、跟踪误差与费率字段齐全。"
            ),
        )
    latest_as_of = max(item.as_of for item in snapshots)
    status = "success" if covered_indices == len(indices) else "partial"
    record_sync(
        "fund_products",
        status,
        latest_as_of,
        f"已为 {covered_indices}/{len(indices)} 个指数同步 {len(snapshots)} 个真实基金候选；缺失指标不参与最终推荐。",
    )
    return {
        "dataset": "fund_products",
        "status": status,
        "updated": len(snapshots),
        "coveredIndices": covered_indices,
        "totalIndices": len(indices),
        "asOf": latest_as_of,
        "failures": failures,
    }


def verify_deposit_sources() -> Dict[str, Any]:
    initialize()
    with connection() as db:
        rows = db.execute(
            "SELECT bank, effective_at, source_url FROM deposit_rates"
        ).fetchall()
    available = 0
    review_required = 0
    today = date.today().isoformat()
    for row in rows:
        previous = get_evidence("deposits", row["bank"])
        request = urllib.request.Request(
            row["source_url"],
            headers={"User-Agent": "Mozilla/5.0 WealthPilot/1.0"},
        )
        try:
            with urllib.request.urlopen(
                request, timeout=15, context=ssl.create_default_context()
            ) as response:
                content = response.read()
                content_hash = _normalized_content_hash(
                    content, response.headers.get("Content-Type", "")
                )
            changed = bool(previous and previous.get("content_hash") and previous["content_hash"] != content_hash)
            status = "review_required" if changed else "source_verified"
            message = (
                "官网正文发生变化，挂牌利率在人工复核前保持原值。"
                if changed
                else "银行官网可访问；展示值为已核验挂牌利率。"
            )
            review_required += int(changed)
            available += 1
            with connection() as db:
                db.execute(
                    "UPDATE deposit_rates SET retrieved_at=? WHERE bank=?",
                    (today, row["bank"]),
                )
            record_evidence(
                dataset="deposits",
                item_key=row["bank"],
                provider="bank_official",
                source_url=row["source_url"],
                as_of=row["effective_at"],
                freshness="fresh",
                fallback_used=False,
                status=status,
                message=message,
                content_hash=content_hash,
            )
        except Exception as exc:
            record_evidence(
                dataset="deposits",
                item_key=row["bank"],
                provider="bank_official",
                source_url=row["source_url"],
                as_of=row["effective_at"],
                freshness="missing",
                fallback_used=False,
                status="unavailable",
                message=f"银行官网暂时不可访问：{type(exc).__name__}",
            )
    status = "success" if available == len(rows) and not review_required else "partial"
    record_sync(
        "deposits",
        status,
        today,
        f"{available}/{len(rows)} 个银行官网可访问；{review_required} 个页面需要人工复核。",
    )
    return {
        "dataset": "deposits",
        "status": status,
        "available": available,
        "total": len(rows),
        "reviewRequired": review_required,
        "asOf": today,
    }


def run_daily_sync() -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    for key, action in (
        ("deposits", verify_deposit_sources),
        ("indices", sync_a_share_indices),
        ("fund_products", sync_index_fund_products),
        ("funds", sync_bond_funds),
    ):
        try:
            results[key] = action()
        except Exception as exc:
            record_sync(key, "blocked", None, str(exc))
            results[key] = {"status": "blocked", "message": str(exc)}
    results["retrievedAt"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return results


if __name__ == "__main__":
    print(json.dumps(run_daily_sync(), ensure_ascii=False, indent=2))
