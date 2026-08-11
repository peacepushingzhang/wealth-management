from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a public-only WealthPilot market snapshot.")
    parser.add_argument("--database", type=Path, default=ROOT / "backend" / "data" / "public-market.sqlite3")
    parser.add_argument("--output", type=Path, default=ROOT / "public" / "market-snapshot.json")
    parser.add_argument("--refresh", action="store_true", help="Refresh free public sources before export.")
    return parser.parse_args()


def merge_by_key(previous: List[Dict[str, Any]], current: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    if not current:
        return previous
    prior = {str(item.get(key)): item for item in previous}
    merged: List[Dict[str, Any]] = []
    for item in current:
        old = prior.get(str(item.get(key)))
        if old and key == "code" and item.get("pePercentile") is None and old.get("pePercentile") is not None:
            merged.append(old)
        else:
            merged.append(item)
    return merged


def main() -> None:
    args = parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    os.environ["WEALTHPILOT_DB_PATH"] = str(args.database.resolve())

    from backend.wealthpilot_api.collectors import run_daily_sync
    from backend.wealthpilot_api.storage import load_workspace

    refresh_result: Dict[str, Any] = {}
    if args.refresh:
        refresh_result = run_daily_sync()
    workspace = load_workspace()

    previous: Dict[str, Any] = {}
    if args.output.exists():
        try:
            previous = json.loads(args.output.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous = {}

    snapshot = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "refreshResult": refresh_result,
        "depositRates": merge_by_key(previous.get("depositRates", []), workspace["depositRates"], "bank"),
        "indices": merge_by_key(previous.get("indices", []), workspace["indices"], "code"),
        "fundProducts": merge_by_key(previous.get("fundProducts", []), workspace["fundProducts"], "code"),
        "bondFunds": merge_by_key(previous.get("bondFunds", []), workspace["bondFunds"], "code"),
        "syncStatus": {
            key: value if value is not None else previous.get("syncStatus", {}).get(key)
            for key, value in workspace["syncStatus"].items()
        },
    }
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
