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
            try:
                wait = float(retry_after) if retry_after else float(2 ** (attempt + 1))
            except (TypeError, ValueError):
                wait = float(2 ** (attempt + 1))
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
    if not isinstance(alpha, dict):
        return None
    is_payload = alpha.get("is") or {}
    checks = is_payload.get("checks", []) if isinstance(is_payload, dict) else []
    if not checks:
        checks = alpha.get("checks", []) or []
    return next(
        (check for check in checks if isinstance(check, dict)
         and check.get("name") == "SELF_CORRELATION"),
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


def _merge_self_correlation(alpha: dict[str, Any], check: dict[str, Any] | None) -> None:
    if check is None:
        return
    is_payload = alpha.setdefault("is", {})
    if not isinstance(is_payload, dict):
        is_payload = {}
        alpha["is"] = is_payload
    checks = is_payload.setdefault("checks", [])
    if not isinstance(checks, list):
        checks = []
        is_payload["checks"] = checks
    for index, existing in enumerate(checks):
        if isinstance(existing, dict) and existing.get("name") == "SELF_CORRELATION":
            checks[index] = check
            break
    else:
        checks.append(check)


def _response_json(response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _retry_after_seconds(response, default: float = 10.0) -> float:
    value = response.headers.get("Retry-After")
    if value is None:
        return default
    try:
        return max(0.5, float(value))
    except (TypeError, ValueError):
        return default


def trigger_and_wait_for_self_correlation(
    session: requests.Session,
    alpha_id: str,
    initial_alpha: dict[str, Any],
    timeout_seconds: float = 900,
    poll_interval_seconds: float = 10,
    send_trigger: bool = True,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Trigger submission checks, then poll BRAIN's submit endpoint for SELF_CORRELATION."""
    current_alpha = initial_alpha
    check = self_correlation_check(current_alpha)
    if numeric_check_value(check) is not None:
        return current_alpha, check

    submit_url = f"{BRAIN_API_BASE}/alphas/{alpha_id}/submit"
    if send_trigger:
        response = _request_with_retry(
            session, "POST", submit_url, allow_redirects=False
        )
        response_payload = _response_json(response)
        response_check = self_correlation_check(response_payload or {})
        _merge_self_correlation(current_alpha, response_check)
        check = self_correlation_check(current_alpha)
        if numeric_check_value(check) is not None:
            return current_alpha, check
        if response.status_code == 403:
            raise RuntimeError(
                f"BRAIN rejected the trigger without a numeric SELF_CORRELATION value: {response.text}"
            )
        if response.status_code not in (200, 201, 202, 303, 503):
            raise RuntimeError(f"Correlation trigger failed: {response.status_code} {response.text}")
        print(f"  Trigger accepted for {alpha_id} (HTTP {response.status_code}); polling {submit_url}.")
    else:
        print(f"  Resuming the in-flight check for {alpha_id} by polling {submit_url}.")

    deadline = time.monotonic() + timeout_seconds
    while True:
        response = _request_with_retry(
            session, "GET", submit_url, allow_redirects=False
        )
        response_payload = _response_json(response)
        response_check = self_correlation_check(response_payload or {})
        _merge_self_correlation(current_alpha, response_check)
        check = self_correlation_check(current_alpha)
        value = numeric_check_value(check)
        if value is not None:
            return current_alpha, check

        if response.status_code == 403:
            raise RuntimeError(
                f"BRAIN returned HTTP 403 without a numeric SELF_CORRELATION value: {response.text}"
            )
        if response.status_code not in (200, 201, 202, 303, 503):
            raise RuntimeError(f"Could not poll correlation result: {response.status_code} {response.text}")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return current_alpha, None
        wait_seconds = min(_retry_after_seconds(response, poll_interval_seconds), remaining)
        print(f"  {alpha_id}: SELF_CORRELATION still pending; checking again in {wait_seconds:g}s.")
        time.sleep(wait_seconds)

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

