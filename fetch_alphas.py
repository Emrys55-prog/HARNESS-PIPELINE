
"""
Fetch Alpha Harness / WorldQuant BRAIN alpha details by ID.

Requires:
    auth.py containing WQSession
    alpha_ids.txt containing one alpha ID per line

Outputs:
    fetched_alphas.json  - complete API responses
    fetched_alphas.csv   - key metrics and expression

Usage:
    python fetch_alphas.py
"""

import csv
import json
import time
from pathlib import Path

import requests

from auth import WQSession, BRAIN_API_BASE


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
IDS_FILE = DATA_DIR / "alpha_ids.txt"
JSON_FILE = DATA_DIR / "fetched_alphas.json"
CSV_FILE = DATA_DIR / "fetched_alphas.csv"

REQUEST_DELAY = 1.0
MAX_RETRIES = 5


def load_ids():
    if not IDS_FILE.exists():
        raise FileNotFoundError(
            f"Missing {IDS_FILE}. Create it with one alpha ID per line."
        )

    ids = []
    for line in IDS_FILE.read_text(encoding="utf-8").splitlines():
        alpha_id = line.strip()
        if alpha_id and not alpha_id.startswith("#"):
            ids.append(alpha_id)

    # Remove duplicates while preserving order
    return list(dict.fromkeys(ids))


def load_cache():
    if not JSON_FILE.exists():
        return {}

    try:
        data = json.loads(JSON_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        print("Warning: cache JSON is invalid; starting a fresh cache.")
        return {}


def fetch_alpha(session, alpha_id):
    url = f"{BRAIN_API_BASE}/alphas/{alpha_id}"

    for attempt in range(MAX_RETRIES):
        try:
            response = session.get(url, timeout=30)

            if response.status_code == 200:
                return response.json()

            if response.status_code == 429:
                wait = float(response.headers.get("Retry-After", 10))
                print(f"Rate limited. Waiting {wait:.1f}s...")
                time.sleep(wait)
                continue

            if response.status_code in (401, 403):
                raise RuntimeError(
                    f"Access denied for {alpha_id}: "
                    f"HTTP {response.status_code}. "
                    "Your session may need re-authentication."
                )

            if response.status_code >= 500:
                wait = min(2 ** (attempt + 1), 60)
                print(
                    f"Server error {response.status_code}; "
                    f"retrying in {wait}s..."
                )
                time.sleep(wait)
                continue

            print(
                f"Failed {alpha_id}: HTTP {response.status_code} "
                f"{response.text[:300]}"
            )
            return None

        except (requests.ConnectionError, requests.Timeout) as exc:
            wait = min(2 ** (attempt + 1), 60)
            print(f"Network error: {exc}. Retrying in {wait}s...")
            time.sleep(wait)

    print(f"Giving up on {alpha_id} after {MAX_RETRIES} attempts.")
    return None


def get_metrics(alpha):
    """Extract commonly useful metrics, tolerating missing fields."""
    is_metrics = alpha.get("is") or {}
    settings = alpha.get("settings") or {}
    regular = alpha.get("regular") or {}

    return {
        "id": alpha.get("id", ""),
        "name": alpha.get("name", ""),
        "status": alpha.get("status", ""),
        "expression": regular.get("code", ""),
        "sharpe": is_metrics.get("sharpe"),
        "fitness": is_metrics.get("fitness"),
        "turnover": is_metrics.get("turnover"),
        "drawdown": is_metrics.get("drawdown"),
        "margin": is_metrics.get("margin"),
        "decay": settings.get("decay"),
        "neutralization": settings.get("neutralization"),
        "region": settings.get("region"),
        "universe": settings.get("universe"),
        "delay": settings.get("delay"),
        "dateCreated": alpha.get("dateCreated", ""),
    }


def save_json(cache):
    JSON_FILE.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def save_csv(cache):
    rows = []

    for alpha_id, alpha in cache.items():
        if alpha.get("_fetch_error"):
            continue
        rows.append(get_metrics(alpha))

    if not rows:
        print("No successful alpha records to write to CSV.")
        return

    fieldnames = list(rows[0].keys())

    with CSV_FILE.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    alpha_ids = load_ids()
    cache = load_cache()

    if not alpha_ids:
        print("No alpha IDs found in alpha_ids.txt.")
        return

    session_manager = WQSession()
    session_manager.login()
    session = session_manager.session

    print(f"IDs supplied: {len(alpha_ids)}")
    print(f"Already cached: {len(cache)}")

    fetched = 0
    failed = 0

    for index, alpha_id in enumerate(alpha_ids, start=1):
        existing = cache.get(alpha_id)

        # Skip successful records; retry records marked as failed
        if existing and not existing.get("_fetch_error"):
            print(f"[{index}/{len(alpha_ids)}] Cached: {alpha_id}")
            continue

        print(f"[{index}/{len(alpha_ids)}] Fetching {alpha_id}...")

        try:
            result = fetch_alpha(session, alpha_id)

            if result is not None:
                cache[alpha_id] = result
                fetched += 1
            else:
                cache[alpha_id] = {
                    "_fetch_error": "Fetch failed; retry on next run."
                }
                failed += 1

        except RuntimeError as exc:
            print(exc)
            failed += 1
            # Stop on session/access problems rather than hammering API
            break

        # Save after each ID so progress survives interruptions
        save_json(cache)
        time.sleep(REQUEST_DELAY)

    save_json(cache)
    save_csv(cache)

    print("\nFinished.")
    print(f"Fetched this run: {fetched}")
    print(f"Failures: {failed}")
    print(f"JSON: {JSON_FILE}")
    print(f"CSV: {CSV_FILE}")


if __name__ == "__main__":
    main()
