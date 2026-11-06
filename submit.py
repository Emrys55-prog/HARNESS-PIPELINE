"""
Stage 7: Submission
----------------------
Submits a single alpha to BRAIN for real. This is the only stage that
commits something live to your account, so it always shows you the
alpha's stats one more time and requires typed confirmation before
submitting — no silent auto-submit, by design (see the pipeline
discussion: BRAIN is meant to evaluate research judgment you actually
applied, not alphas you never looked at).

Also verifies AFTER submitting that the alpha actually went ACTIVE —
a 201 response from BRAIN only means the request was accepted, not
that the alpha is live. If SELF_CORRELATION or another check fails
post-submission, BRAIN can leave it UNSUBMITTED even after a 201.

Usage:
    python submit.py <alpha_id>
    python submit.py akbxEmxw
"""

import sys
import time

import requests

from auth import WQSession

BRAIN_API_BASE = "https://api.worldquantbrain.com"


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
    for c in checks:
        mark = "PASS" if c.get("result") == "PASS" else c.get("result", "?")
        print(f"  [{mark}] {c.get('name')}  {c.get('value', '')}")
    print("=" * 60)


def submit_alpha(session: requests.Session, alpha_id: str) -> None:
    resp = _request_with_retry(session, "POST", f"{BRAIN_API_BASE}/alphas/{alpha_id}/submit")

    if resp.status_code == 403:
        print("\nBRAIN REJECTED the submission (403) — nothing went live. Failed checks:")
        try:
            data = resp.json()
            checks = data.get("is", {}).get("checks", [])
            for c in checks:
                if c.get("result") == "FAIL":
                    print(f"  [FAIL] {c.get('name')}  value={c.get('value')}  limit={c.get('limit')}")
            print("\nThis alpha needs more work before it can be submitted — "
                  "see the failed checks above for what to fix.")
        except Exception:
            print(f"  (raw response: {resp.text})")
        return

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Submit failed: {resp.status_code} {resp.text}")

    print(f"\nSubmit request accepted (status {resp.status_code}). "
          f"Note: this does NOT yet mean the alpha is live — verifying...\n")

    # A 201 only means BRAIN accepted the request. Poll to confirm the
    # alpha actually reaches ACTIVE, and surface SELF_CORRELATION if it
    # fails there instead. With a larger live portfolio, SELF_CORRELATION
    # takes longer to compute (checking against more existing alphas) —
    # 60 attempts x 15s = 15 minutes, well above what's needed early on
    # but realistic once you have a couple dozen alphas active.
    max_attempts = 60
    try:
        for attempt in range(max_attempts):
            time.sleep(15)
            alpha = get_alpha(session, alpha_id)
            status = alpha.get("status")
            print(f"  [{attempt+1}/{max_attempts}] status = {status}")

            if status == "ACTIVE":
                print(f"\nSUCCESS — alpha {alpha_id} is now ACTIVE.")
                return

            checks = alpha.get("is", {}).get("checks", [])
            self_corr = next((c for c in checks if c.get("name") == "SELF_CORRELATION"), None)
            if self_corr and self_corr.get("result") == "FAIL":
                print(f"\nSubmission did not go live: SELF_CORRELATION failed "
                      f"(value={self_corr.get('value')}). This means it's too "
                      f"correlated with an alpha you already have active.")
                return

        print(f"\nStill not ACTIVE after ~{max_attempts * 15}s of polling. Status was last: {status}. "
              f"This usually just means SELF_CORRELATION is still computing against your growing "
              f"portfolio — check again in a few minutes with: python check_status.py {alpha_id} "
              f"(read-only, won't re-submit). Or check "
              f"https://platform.worldquantbrain.com/alpha/{alpha_id} directly.")
    except KeyboardInterrupt:
        print(f"\n\nStopped waiting on {alpha_id} (Ctrl+C) — the submission itself is "
              f"still pending on BRAIN's side, nothing was cancelled by this. Check its "
              f"real status later with: python check_status.py {alpha_id}")
        return


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python submit.py <alpha_id>")
        sys.exit(1)

    alpha_id = sys.argv[1]

    session = WQSession()
    session.login()

    alpha = get_alpha(session.session, alpha_id)
    show_summary(alpha)

    confirm = input("\nType 'yes' to submit this alpha for real, anything else to cancel: ")
    if confirm.strip().lower() != "yes":
        print("Cancelled — nothing was submitted.")
        sys.exit(0)

    submit_alpha(session.session, alpha_id)