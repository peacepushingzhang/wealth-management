from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "backend" / "data" / "wealthpilot.sqlite3"
SCHEMA = ROOT / "backend" / "schema.sql"
OWNER_ID = "owner_local"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def database_path() -> Path:
    configured = os.getenv("WEALTHPILOT_DB_PATH")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_DB


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


DEPOSIT_SEED = [
    ("工商银行", "ICBC", .65, .85, .95, 1.05, 1.25, 1.30, "2025-05-20", "2026-08-11", "https://www.icbc.com.cn/page/1098160857085153280.html"),
    ("农业银行", "ABC", .65, .85, .95, 1.05, 1.25, 1.30, "2025-05-20", "2026-08-11", "https://www.abchina.com/zt/PersonalServices/SvcBulletin/202505/t20250519_2445034.htm"),
    ("中国银行", "BOC", .65, .85, .95, 1.05, 1.25, 1.30, "2025-05-20", "2026-08-11", "https://www.boc.cn/fimarkets/lilv/fd31/202505/t20250520_25356440.html"),
    ("建设银行", "CCB", .65, .85, .95, 1.05, 1.25, 1.30, "2025-05-20", "2026-08-11", "https://www.ccb.com/chn/2025-05/19/article_2025051921024471224.shtml"),
    ("交通银行", "BOCOM", .65, .85, .95, 1.05, 1.25, 1.30, "2025-05-20", "2026-08-11", "https://bankcomm.com/BankCommSite/shtml/jyjr/cn/7158/7825/5063992.shtml?channelId=7158"),
    ("邮储银行", "PSBC", .65, .86, .98, 1.05, 1.25, 1.30, "2025-05-20", "2026-08-11", "https://www.psbc.com/cn/gyyc/zygg/202505/t20250519_331570.html"),
    ("招商银行", "CMB", .65, .85, .95, 1.05, 1.25, 1.30, "2025-05-20", "2026-08-11", "https://fin.paas.cmbchina.com/fininfo/interestrate"),
]

INDEX_SEED = [
    ("000300.SH", "沪深300", "A股"),
    ("000510.CSI", "中证A500", "A股"),
    ("000905.SH", "中证500", "A股"),
    ("000852.SH", "中证1000", "A股"),
    ("399006.SZ", "创业板指", "A股"),
    ("000688.SH", "科创50", "A股"),
    ("SPX", "标普500", "美股"),
    ("NDX", "纳斯达克100", "美股"),
    ("DJI", "道琼斯工业指数", "美股"),
    ("RUT", "罗素2000", "美股"),
]

ASSET_SEED = [
    ("cash", "liquidity", "流动现金", 0, None, "朝朝宝类 + 活期", "#d9de68"),
    ("deposit", "deposit", "定期存款", 0, None, "6–24个月阶梯", "#91cda0"),
    ("index", "index", "宽基指数", 0, None, "长期定投", "#82a9d7"),
    ("bond", "bond", "债券基金", 0, None, "中短久期", "#b5a0d9"),
    ("stock", "stock", "股票", 0, None, "小比例持仓", "#dc9d75"),
    ("housing-fund", "housingFund", "公积金", 0, None, "非现金账户", "#71827c"),
]


def initialize() -> None:
    with connection() as db:
        db.executescript(SCHEMA.read_text(encoding="utf-8"))
        timestamp = now_iso()
        current_month = datetime.now().strftime("%Y-%m")
        db.execute(
            """INSERT OR IGNORE INTO monthly_records VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (OWNER_ID, current_month, "", "student", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, timestamp),
        )
        db.executemany(
            """INSERT OR IGNORE INTO asset_positions
            (user_id, id, strategy, label, value, cost, note, tone, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(OWNER_ID, *row, timestamp) for row in ASSET_SEED],
        )
        db.executemany(
            """INSERT OR IGNORE INTO deposit_rates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            DEPOSIT_SEED,
        )
        db.executemany("INSERT OR IGNORE INTO index_catalog VALUES (?, ?, ?)", INDEX_SEED)
        db.executemany(
            """INSERT OR IGNORE INTO index_valuations
            (code, pe, pe_percentile, pb, pb_percentile, as_of, source_url, updated_at)
            VALUES (?, NULL, NULL, NULL, NULL, NULL, NULL, ?)""",
            [(code, timestamp) for code, _, _ in INDEX_SEED],
        )


def _row_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return dict(row)


def _evidence_payload(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {
        "provider": row["provider"],
        "sourceUrl": row["source_url"],
        "asOf": row["as_of"],
        "retrievedAt": row["retrieved_at"],
        "freshness": row["freshness"],
        "fallbackUsed": bool(row["fallback_used"]),
        "status": row["status"],
        "message": row["message"],
    }


def load_workspace(user_id: str = OWNER_ID) -> Dict[str, Any]:
    initialize()
    with connection() as db:
        month = db.execute(
            "SELECT * FROM monthly_records WHERE user_id=? ORDER BY month DESC LIMIT 1", (user_id,)
        ).fetchone()
        assets = db.execute(
            "SELECT * FROM asset_positions WHERE user_id=? ORDER BY rowid", (user_id,)
        ).fetchall()
        deposits = db.execute("SELECT * FROM deposit_rates ORDER BY rowid").fetchall()
        indices = db.execute(
            """SELECT c.code, c.name, c.market, v.pe, v.pe_percentile, v.pb,
                      v.pb_percentile, v.as_of, v.source_url
               FROM index_catalog c LEFT JOIN index_valuations v ON c.code=v.code
               ORDER BY c.rowid"""
        ).fetchall()
        funds = db.execute("SELECT * FROM fund_products ORDER BY rowid").fetchall()
        bonds = db.execute("SELECT * FROM bond_fund_quotes ORDER BY rowid").fetchall()
        purchases = db.execute(
            "SELECT * FROM index_purchases WHERE user_id=? ORDER BY purchase_date DESC, id DESC",
            (user_id,),
        ).fetchall()
        sync = {row["dataset"]: _row_dict(row) for row in db.execute("SELECT * FROM sync_runs").fetchall()}
        evidence = {
            (row["dataset"], row["item_key"]): row
            for row in db.execute("SELECT * FROM market_evidence").fetchall()
        }

    if month is None:
        raise RuntimeError("No monthly record is available")
    return {
        "monthRecord": {
            "month": month["month"], "city": month["city"], "employmentStage": month["employment_stage"],
            "salary": month["salary"], "housingFund": month["housing_fund"], "allowance": month["allowance"],
            "otherIncome": month["other_income"], "housing": month["housing"], "food": month["food"],
            "transport": month["transport"], "learning": month["learning"], "otherExpense": month["other_expense"],
            "confirmed": bool(month["confirmed"]),
        },
        "assets": [{
            "id": row["id"], "strategy": row["strategy"], "label": row["label"], "value": row["value"],
            **({"cost": row["cost"]} if row["cost"] is not None else {}), "note": row["note"], "tone": row["tone"],
        } for row in assets],
        "depositRates": [{
            "bank": row["bank"], "short": row["short"], "threeMonth": row["three_month"],
            "sixMonth": row["six_month"], "oneYear": row["one_year"], "twoYear": row["two_year"],
            "threeYear": row["three_year"], "fiveYear": row["five_year"], "effectiveAt": row["effective_at"],
            "retrievedAt": row["retrieved_at"], "sourceUrl": row["source_url"],
            "evidence": _evidence_payload(evidence.get(("deposits", row["bank"]))),
        } for row in deposits],
        "indices": [{
            "code": row["code"], "name": row["name"], "market": row["market"], "pe": row["pe"],
            "pePercentile": row["pe_percentile"], "pb": row["pb"], "pbPercentile": row["pb_percentile"],
            "asOf": row["as_of"], "sourceUrl": row["source_url"],
            "evidence": _evidence_payload(evidence.get(("indices", row["code"]))),
        } for row in indices],
        "fundProducts": [{
            "code": row["code"], "name": row["name"], "indexCode": row["index_code"], "venue": row["venue"],
            "scaleBillion": row["scale_billion"], "trackingError": row["tracking_error"],
            "totalFee": row["total_fee"], "asOf": row["as_of"], "sourceUrl": row["source_url"],
            "evidence": _evidence_payload(evidence.get(("fund_products", row["code"]))),
        } for row in funds],
        "purchases": [{
            "id": row["id"], "purchaseDate": row["purchase_date"], "indexCode": row["index_code"],
            "fundCode": row["fund_code"], "fundName": row["fund_name"], "venue": row["venue"],
            "shares": row["shares"], "amount": row["amount"], "createdAt": row["created_at"],
        } for row in purchases],
        "bondFunds": [{
            "code": row["code"], "name": row["name"], "issuer": row["issuer"],
            "dailyChange": row["daily_change"], "oneYearReturn": row["one_year_return"],
            "maxDrawdown": row["max_drawdown"], "nav": row["nav"], "asOf": row["as_of"],
            "sourceUrl": row["source_url"],
            "evidence": _evidence_payload(evidence.get(("funds", row["code"]))),
        } for row in bonds],
        "syncStatus": {
            "depositsAt": sync.get("deposits", {}).get("as_of") or "2026-08-11",
            "indicesAt": sync.get("indices", {}).get("as_of"),
            "fundsAt": sync.get("funds", {}).get("as_of"),
            "fundProductsAt": sync.get("fund_products", {}).get("as_of"),
            "nextRunAt": "每日 07:30",
        },
    }


def save_manual_index_valuation(
    code: str,
    *,
    pe_percentile: float,
    as_of: str,
    pe: Optional[float] = None,
    source_url: Optional[str] = None,
) -> None:
    initialize()
    with connection() as db:
        exists = db.execute("SELECT 1 FROM index_catalog WHERE code=?", (code,)).fetchone()
        if exists is None:
            raise ValueError("Unknown index code")
        db.execute(
            """UPDATE index_valuations SET pe=?, pe_percentile=?, as_of=?, source_url=?, updated_at=?
               WHERE code=?""",
            (pe, pe_percentile, as_of, source_url, now_iso(), code),
        )


def save_index_purchase(payload: Dict[str, Any], user_id: str = OWNER_ID) -> Dict[str, Any]:
    initialize()
    timestamp = now_iso()
    with connection() as db:
        cursor = db.execute(
            """INSERT INTO index_purchases
               (user_id, purchase_date, index_code, fund_code, fund_name, venue, shares, amount, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                payload["purchaseDate"],
                payload["indexCode"],
                payload["fundCode"],
                payload["fundName"],
                payload["venue"],
                payload["shares"],
                payload.get("amount"),
                timestamp,
            ),
        )
        purchase_id = cursor.lastrowid
    return {
        "id": purchase_id,
        **payload,
        "createdAt": timestamp,
    }


def save_personal_workspace(workspace: Dict[str, Any], user_id: str = OWNER_ID) -> None:
    month = workspace["monthRecord"]
    assets = workspace["assets"]
    timestamp = now_iso()
    with connection() as db:
        db.execute(
            """INSERT INTO monthly_records
            (user_id, month, city, employment_stage, salary, housing_fund, allowance, other_income,
             housing, food, transport, learning, other_expense, confirmed, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, month) DO UPDATE SET
              city=excluded.city, employment_stage=excluded.employment_stage, salary=excluded.salary,
              housing_fund=excluded.housing_fund, allowance=excluded.allowance, other_income=excluded.other_income,
              housing=excluded.housing, food=excluded.food, transport=excluded.transport, learning=excluded.learning,
              other_expense=excluded.other_expense, confirmed=excluded.confirmed, updated_at=excluded.updated_at""",
            (user_id, month["month"], month["city"], month["employmentStage"], month["salary"],
             month["housingFund"], month["allowance"], month["otherIncome"], month["housing"], month["food"],
             month["transport"], month["learning"], month["otherExpense"], int(month["confirmed"]), timestamp),
        )
        db.execute("DELETE FROM asset_positions WHERE user_id=?", (user_id,))
        db.executemany(
            """INSERT INTO asset_positions
            (user_id, id, strategy, label, value, cost, note, tone, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(user_id, item["id"], item["strategy"], item["label"], item["value"], item.get("cost"),
              item.get("note", ""), item["tone"], timestamp) for item in assets],
        )


def record_sync(dataset: str, status: str, as_of: Optional[str], message: str) -> None:
    timestamp = now_iso()
    with connection() as db:
        db.execute(
            """INSERT INTO sync_runs(dataset, status, started_at, finished_at, as_of, message)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(dataset) DO UPDATE SET status=excluded.status, started_at=excluded.started_at,
              finished_at=excluded.finished_at, as_of=excluded.as_of, message=excluded.message""",
            (dataset, status, timestamp, timestamp, as_of, message),
        )


def get_evidence(dataset: str, item_key: str) -> Optional[Dict[str, Any]]:
    initialize()
    with connection() as db:
        row = db.execute(
            "SELECT * FROM market_evidence WHERE dataset=? AND item_key=?",
            (dataset, item_key),
        ).fetchone()
    return dict(row) if row is not None else None


def record_evidence(
    *,
    dataset: str,
    item_key: str,
    provider: Optional[str],
    source_url: Optional[str],
    as_of: Optional[str],
    freshness: str,
    fallback_used: bool,
    status: str,
    message: str,
    content_hash: Optional[str] = None,
) -> None:
    timestamp = now_iso()
    with connection() as db:
        db.execute(
            """INSERT INTO market_evidence
            (dataset, item_key, provider, source_url, as_of, retrieved_at, freshness,
             fallback_used, status, message, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dataset, item_key) DO UPDATE SET
              provider=COALESCE(excluded.provider, market_evidence.provider),
              source_url=COALESCE(excluded.source_url, market_evidence.source_url),
              as_of=COALESCE(excluded.as_of, market_evidence.as_of),
              retrieved_at=excluded.retrieved_at, freshness=excluded.freshness,
              fallback_used=excluded.fallback_used, status=excluded.status,
              message=excluded.message,
              content_hash=COALESCE(excluded.content_hash, market_evidence.content_hash)""",
            (
                dataset,
                item_key,
                provider,
                source_url,
                as_of,
                timestamp,
                freshness,
                int(fallback_used),
                status,
                message,
                content_hash,
            ),
        )
