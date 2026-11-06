"""
Stage 2: Field Discovery
-------------------------
Fetches BRAIN's data fields for a given region/universe/delay and caches
them locally as JSON, so later stages (expression generation, correlation
checks) don't have to hit the API every time.

Usage:
    from auth import WQSession
    from fields import fetch_fields

    session = WQSession()
    session.login()

    fields = fetch_fields(session.session, region="USA", universe="TOP3000", delay=1)
    print(f"Cached {len(fields)} fields.")
"""

import json
import time
from pathlib import Path

import requests

BRAIN_API_BASE = "https://api.worldquantbrain.com"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIELDS_CACHE_DIR = PROJECT_ROOT / "data" / "field_cache"


def _cache_path(region: str, universe: str, delay: int) -> Path:
    FIELDS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return FIELDS_CACHE_DIR / f"fields_{region}_{universe}_d{delay}.json"


def _get_with_retry(
    session: requests.Session,
    url: str,
    params: dict,
    max_retries: int = 6,
) -> requests.Response:
    """GET with automatic backoff on 429 (rate limit) responses.
    Respects the Retry-After header when BRAIN sends one, otherwise
    backs off exponentially (2s, 4s, 8s, ...)."""

    for attempt in range(max_retries):
        resp = session.get(url, params=params)

        if resp.status_code == 200:
            return resp

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if retry_after else (2 ** (attempt + 1))
            print(f"\nRate limited — waiting {wait}s before retrying "
                  f"(attempt {attempt + 1}/{max_retries})...")
            time.sleep(wait)
            continue

        # Any other error: don't retry, fail loudly
        raise RuntimeError(f"Field fetch failed: {resp.status_code} {resp.text}")

    raise RuntimeError(f"Field fetch still rate-limited after {max_retries} retries.")


def fetch_fields(
    session: requests.Session,
    region: str = "USA",
    universe: str = "TOP3000",
    delay: int = 1,
    instrument_type: str = "EQUITY",
    force_refresh: bool = False,
    page_size: int = 50,
) -> list[dict]:
    """Fetch all data fields for the given settings, using a local cache
    unless force_refresh=True. Returns a list of field dicts, each with
    at least 'id', 'description', 'dataset', and 'type'."""

    cache_file = _cache_path(region, universe, delay)

    if cache_file.exists() and not force_refresh:
        cached = json.loads(cache_file.read_text())
        print(f"Loaded {len(cached)} fields from cache ({cache_file}).")
        return cached

    print("Fetching fields from BRAIN API (this can take a few minutes)...")

    params = {
        "instrumentType": instrument_type,
        "region": region,
        "delay": delay,
        "universe": universe,
        "limit": page_size,
        "offset": 0,
    }

    all_fields = []
    while True:
        resp = _get_with_retry(session, f"{BRAIN_API_BASE}/data-fields", params)

        payload = resp.json()
        batch = payload.get("results", [])
        all_fields.extend(batch)

        total = payload.get("count", len(all_fields))
        print(f"  {len(all_fields)} / {total} fields fetched...", end="\r")

        if not batch or len(all_fields) >= total:
            break

        params["offset"] += page_size
        time.sleep(1)  # be polite to the API between pages

    print(f"\nFetched {len(all_fields)} fields total.")
    cache_file.write_text(json.dumps(all_fields, indent=2))
    print(f"Cached to {cache_file}")

    return all_fields


if __name__ == "__main__":
    from auth import WQSession

    session = WQSession()
    session.login()

    fields = fetch_fields(session.session, region="USA", universe="TOP3000", delay=1)

    # Quick sanity check: show a few field IDs so you can eyeball the format
    print("\nSample fields:")
    for f in fields[:10]:
        print(f"  {f.get('id')}: {f.get('description')}")