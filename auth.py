"""
Stage 1: Authentication
------------------------
Logs into WorldQuant BRAIN, handles the Persona biometric verification
step if your account requires it, and caches session cookies to disk
so you don't have to re-authenticate every run.

Usage:
    from auth import WQSession

    session = WQSession(credentials_file="credentials.json")
    session.login()

    # session.session is a requests.Session you can reuse in later stages
    resp = session.session.get("https://api.worldquantbrain.com/users/self")
    print(resp.json())
"""

import json
import pickle
import time
from pathlib import Path

import requests

BRAIN_API_BASE = "https://api.worldquantbrain.com"
COOKIE_CACHE_PATH = Path(".wq_session_cookies.pkl")


class WQSession:
    def __init__(self, credentials_file: str = "credentials.json"):
        self.credentials_file = Path(credentials_file)
        self.session = requests.Session()

    def _load_credentials(self) -> tuple[str, str]:
        if not self.credentials_file.exists():
            raise FileNotFoundError(
                f"Missing {self.credentials_file}. Create it as:\n"
                '  ["your_email@example.com", "your_password"]'
            )
        email, password = json.loads(self.credentials_file.read_text())
        return email, password

    def _load_cached_cookies(self, verify: bool = True) -> bool:
        """Try reusing a saved session so we don't log in every run.
        verify=False skips the /users/self check (saves an API call
        when you're confident the cached session is still fresh)."""
        if not COOKIE_CACHE_PATH.exists():
            return False
        try:
            with open(COOKIE_CACHE_PATH, "rb") as f:
                cookies = pickle.load(f)
            self.session.cookies.update(cookies)

            if not verify:
                print("Loaded cached session (unverified).")
                return True

            # Confirm the cached session is still valid
            resp = self.session.get(f"{BRAIN_API_BASE}/users/self")
            if resp.status_code == 200:
                print("Reused cached session — no login needed.")
                return True
        except Exception:
            pass
        return False

    def _save_cookies(self) -> None:
        with open(COOKIE_CACHE_PATH, "wb") as f:
            pickle.dump(self.session.cookies, f)

    def _post_with_network_retry(self, url: str, max_retries: int = 5, **kwargs):
        """POST with backoff on connection errors/timeouts — handles brief
        WiFi drops or BRAIN being momentarily slow to respond, so a single
        network blip doesn't kill an overnight run."""
        for attempt in range(max_retries):
            try:
                return self.session.post(url, timeout=30, **kwargs)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                wait = 2 ** (attempt + 2)  # 4s, 8s, 16s, 32s, 64s
                if attempt == max_retries - 1:
                    raise
                print(f"Network error ({e.__class__.__name__}) — retrying in {wait}s "
                      f"(attempt {attempt + 1}/{max_retries})...")
                time.sleep(wait)

    def login(self, poll_interval: int = 5, timeout: int = 300, verify_cache: bool = True) -> None:
        """Authenticate with BRAIN. Blocks until login (and any required
        Persona verification) completes, or raises after `timeout` seconds.
        Set verify_cache=False to skip the extra API call that checks a
        cached session is still valid (useful if you're rate-limited and
        confident the cache is fresh)."""

        if self._load_cached_cookies(verify=verify_cache):
            return

        email, password = self._load_credentials()

        resp = self._post_with_network_retry(
            f"{BRAIN_API_BASE}/authentication", auth=(email, password)
        )

        if resp.status_code == 201:
            print("Logged in successfully.")
            self._save_cookies()
            return

        if resp.status_code == 401 and "location" in resp.headers.get("WWW-Authenticate", ""):
            # Some accounts require Persona biometric verification.
            persona_url = resp.json().get("persona", {}).get("url")
            if not persona_url:
                raise RuntimeError(f"Login failed and no Persona URL was returned: {resp.text}")

            print("Persona verification required. Open this link and complete it:")
            print(f"  {persona_url}")
            print("Waiting for verification to complete...")

            elapsed = 0
            while elapsed < timeout:
                time.sleep(poll_interval)
                elapsed += poll_interval
                check = self.session.post(f"{BRAIN_API_BASE}/authentication")
                if check.status_code == 201:
                    print("Verification complete — logged in.")
                    self._save_cookies()
                    return

            raise TimeoutError("Persona verification was not completed in time.")

        raise RuntimeError(f"Login failed: {resp.status_code} {resp.text}")


if __name__ == "__main__":
    session = WQSession()
    session.login()
    me = session.session.get(f"{BRAIN_API_BASE}/users/self")
    print(me.json())