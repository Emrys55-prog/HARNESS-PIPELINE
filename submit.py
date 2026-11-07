"""Review, submit, and verify one WorldQuant BRAIN alpha."""

import math
import sys
import time
from typing import Any

import requests

from auth import WQSession

BRAIN_API_BASE = "https://api.worldquantbrain.com"
STATUS_CHECK_ATTEMPTS = 1
STATUS_CHECK_INTERVAL_SECONDS = 15


def _request_with_retry(session, method, url, max_retries=6, **kwargs):
    kwargs.setdefault("timeout", 60)
    for attempt in range(max_retries):
        try:
            resp = session.request(method, url, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            wait = 2 ** (attempt + 2)
            print(f"  Network error ({e.__class__.__name__}) — retrying in {wait}s...")
            time.sleep(wait)
            continue
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if retry_after else (2 ** (attempt + 1))
            print(f"  Rate limited — waiting {wait}s...")
            time.sleep(wait)
            continue
        return resp
    raise RuntimeError(f"Still failing after {max_retries} retries: {url}")


def get_alpha(session: requests.Session, alpha_id: str) -> dict:
    resp = _request_with_retry(session, "GET", f"{BRAIN_API_BASE}/alphas/{alpha_id}")
    if resp.status_code != 200:
        raise RuntimeError(f"Could not fetch alpha {alpha_id}: {resp.status_code} {resp.text}")
    return resp.json()


def self_correlation_check(alpha: dict) -> dict[str, Any] | None:
    checks = alpha.get("is", {}).get("checks", []) or []
    return next(
        (check for check in checks if check.get("name") == "SELF_CORRELATION"),
        None,
    )


def numeric_check_value(check: dict[str, Any] | None) -> float | None:
    if not check:
        return None
    try:
        value = float(check.get("value"))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def trigger_and_wait_for_self_correlation(
    session: requests.Session,
    alpha_id: str,
    initial_alpha: dict[str, Any],
    timeout_seconds: float = 900,
    poll_interval_seconds: float = 15,
    send_trigger: bool = True,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Trigger a BRAIN check, then wait for its numeric SELF_CORRELATION value."""
    current_alpha = initial_alpha
    existing_check = self_correlation_check(current_alpha)
    if numeric_check_value(existing_check) is not None:
        return current_alpha, existing_check

    if send_trigger:
        response = _request_with_retry(
            session, "POST", f"{BRAIN_API_BASE}/alphas/{alpha_id}/submit"
        )
    else:
        response = None

    if response is not None and response.status_code == 403:
        try:
            rejected_alpha = response.json()
            if isinstance(rejected_alpha, dict) and rejected_alpha.get("is"):
                current_alpha = rejected_alpha
                existing_check = self_correlation_check(current_alpha)
                if numeric_check_value(existing_check) is not None:
                    return current_alpha, existing_check
        except (ValueError, TypeError):
            pass
        print(f"  BRAIN rejected {alpha_id}; waiting for the check value to appear.")
    elif response is not None and response.status_code not in (200, 201):
        raise RuntimeError(f"Correlation trigger failed: {response.status_code} {response.text}")
    elif response is not None:
        print(f"  Correlation check triggered for {alpha_id} (HTTP {response.status_code}).")
    else:
        print(f"  Continuing to wait for the existing check on {alpha_id}.")

    deadline = time.monotonic() + timeout_seconds
    while True:
        check = self_correlation_check(current_alpha)
        value = numeric_check_value(check)
        if value is not None:
            return current_alpha, check

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return current_alpha, None

        time.sleep(min(poll_interval_seconds, remaining))
        current_alpha = get_alpha(session, alpha_id)


def show_summary(alpha: dict) -> None:
    is_stats = alpha.get("is", {})
    checks = is_stats.get("checks", [])

    print("=" * 60)
    print("FINAL REVIEW BEFORE SUBMISSION")
    print("=" * 60)
    print(f"Expression : {alpha.get('regular', {}).get('code', '(unknown)')}")
    print(f"Alpha ID   : {alpha.get('id')}")
    print(f"Status     : {alpha.get('status')}")
    print(f"Sharpe     : {is_stats.get('sharpe')}")
    print(f"Fitness    : {is_stats.get('fitness')}")
    print(f"Turnover   : {is_stats.get('turnover')}")
    print(f"Drawdown   : {is_stats.get('drawdown')}")
    print(f"Margin     : {is_stats.get('margin')}")
    print(f"\nChecks ({sum(1 for c in checks if c.get('result') == 'PASS')}/{len(checks)} passed):")
    for check in checks:
        mark = "PASS" if check.get("result") == "PASS" else check.get("result", "?")
        print(f"  [{mark}] {check.get('name')}  {check.get('value', '')}")
    print("=" * 60)


def _failed_checks(alpha: dict) -> list[dict[str, Any]]:
    checks = alpha.get("is", {}).get("checks", [])
    return [check for check in checks if check.get("result") == "FAIL"]


def submit_alpha(session: requests.Session, alpha_id: str) -> dict[str, Any]:
    """Submit once, then check once for ACTIVE status."""
    resp = _request_with_retry(session, "POST", f"{BRAIN_API_BASE}/alphas/{alpha_id}/submit")

    if resp.status_code == 403:
        try:
            rejected = resp.json()
            failed_checks = _failed_checks(rejected)
        except Exception:
            failed_checks = []
        print("\nBRAIN rejected the submission (403); it did not become active.")
        for check in failed_checks:
            print(f"  [FAIL] {check.get('name')}  value={check.get('value')}  limit={check.get('limit')}")
        if not failed_checks:
            print(f"  {resp.text}")
        return {
            "alpha_id": alpha_id,
            "outcome": "failed",
            "brain_status": "UNSUBMITTED",
            "attempts": 0,
            "message": "BRAIN rejected the submission request (HTTP 403).",
            "failed_checks": failed_checks,
        }

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Submit failed: {resp.status_code} {resp.text}")

    print(f"\nSubmit request accepted (status {resp.status_code}); checking for ACTIVE status.\n")
    last_alpha: dict[str, Any] = {}
    last_status = "UNKNOWN"

    try:
        for attempt in range(1, STATUS_CHECK_ATTEMPTS + 1):
            time.sleep(STATUS_CHECK_INTERVAL_SECONDS)
            last_alpha = get_alpha(session, alpha_id)
            last_status = str(last_alpha.get("status") or "UNKNOWN")
            print(f"  [{attempt}/{STATUS_CHECK_ATTEMPTS}] status = {last_status}")

            if last_status == "ACTIVE":
                print(f"\nSUCCESS — alpha {alpha_id} is ACTIVE.")
                return {
                    "alpha_id": alpha_id,
                    "outcome": "active",
                    "brain_status": last_status,
                    "attempts": attempt,
                    "message": "BRAIN reports the alpha as ACTIVE.",
                    "failed_checks": [],
                }
    except KeyboardInterrupt:
        print(f"\nVerification interrupted for {alpha_id}; it will be recorded as failed/unconfirmed.")
        return {
            "alpha_id": alpha_id,
            "outcome": "failed",
            "brain_status": last_status,
            "attempts": attempt - 1,
            "message": "Verification was interrupted before ACTIVE status was confirmed.",
            "failed_checks": _failed_checks(last_alpha),
        }

    failed_checks = _failed_checks(last_alpha)
    if last_status == "UNSUBMITTED":
        self_corr = next(
            (check for check in failed_checks if check.get("name") == "SELF_CORRELATION"),
            None,
        )
        if self_corr:
            message = (
                "BRAIN kept the alpha UNSUBMITTED after one status check; "
                f"SELF_CORRELATION failed (value={self_corr.get('value')}, "
                f"limit={self_corr.get('limit')})."
            )
        else:
            message = "BRAIN kept the alpha UNSUBMITTED after one status check."
    else:
        message = (
            f"BRAIN did not report ACTIVE after one status check; "
            f"final status was {last_status}."
        )

    print(f"\nFAILED — {message}")
    return {
        "alpha_id": alpha_id,
        "outcome": "failed",
        "brain_status": last_status,
        "attempts": STATUS_CHECK_ATTEMPTS,
        "message": message,
        "failed_checks": failed_checks,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python submit.py <alpha_id>")
        sys.exit(1)

    alpha_id = sys.argv[1]
    session = WQSession()
    session.login()
    alpha = get_alpha(session.session, alpha_id)
    show_summary(alpha)

    confirm = input("\nType 'yes' to submit this alpha, anything else to cancel: ")
    if confirm.strip().lower() != "yes":
        print("Cancelled — nothing was submitted.")
        sys.exit(0)

    result = submit_alpha(session.session, alpha_id)
    print(f"Outcome: {result['outcome']} ({result['brain_status']})")

