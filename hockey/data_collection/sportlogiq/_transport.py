"""HTTP plumbing shared by every resource: auth, retries, error handling.

Auth is cookie-based — ``POST /api/v3/user/login`` sets four Cognito JWT
cookies plus CloudFront signing cookies on the session. Login is lazy (first
request) and replayed once on a 401, so a long-lived client survives token
expiry without the caller noticing.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests

from hockey.config.settings import _find_dotenv, _load_dotenv_if_present

from .filters import Params


class SportlogiqError(RuntimeError):
    """Non-200 response from the API."""

    def __init__(self, status: int, url: str, body: str) -> None:
        super().__init__(f"HTTP {status} for {url}: {body[:500]}")
        self.status = status
        self.url = url
        self.body = body


class Transport:
    """Authenticated ``requests`` session with retry/backoff.

    One instance is shared by all resources hanging off a client, so there is a
    single login and a single cookie jar.
    """

    BASE_URL = "https://app.sportlogiq.com"

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        *,
        timeout: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        dotenv = _find_dotenv(Path(__file__).resolve().parent)
        if dotenv:
            _load_dotenv_if_present(dotenv)

        self._username = username or os.getenv("SPORTLOGIQ_USERNAME")
        self._password = password or os.getenv("SPORTLOGIQ_PWD")
        if not self._username or not self._password:
            raise EnvironmentError(
                "SPORTLOGIQ_USERNAME and SPORTLOGIQ_PWD must be set in the "
                "environment or passed explicitly."
            )

        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self._logged_in = False

    def login(self) -> None:
        url = f"{self.BASE_URL}/api/v3/user/login"
        response = self.session.post(
            url,
            json={"username": self._username, "password": self._password},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise SportlogiqError(response.status_code, url, response.text)
        self._logged_in = True

    def logout(self) -> None:
        self.session.post(f"{self.BASE_URL}/api/v3/user/logout", timeout=self.timeout)
        self._logged_in = False

    def get(self, path: str, params: Params | None = None) -> Any:
        """GET a v3 path and return parsed JSON.

        Also the escape hatch for endpoints no resource wraps yet.
        """
        return self._request(path, params or [])

    def _request(self, path: str, params: Params, _retried_auth: bool = False) -> Any:
        if not self._logged_in:
            self.login()

        url = f"{self.BASE_URL}{path}"
        response = None
        for attempt in range(self.max_retries):
            response = self.session.get(url, params=params, timeout=self.timeout)

            if response.status_code == 401 and not _retried_auth:
                # Cookies expired — log in again and replay once.
                self._logged_in = False
                return self._request(path, params, _retried_auth=True)

            if response.status_code == 429:
                time.sleep(int(response.headers.get("Retry-After", 1)))
                continue

            if response.status_code >= 500 and attempt < self.max_retries - 1:
                time.sleep(2**attempt)
                continue

            if response.status_code != 200:
                raise SportlogiqError(response.status_code, response.url, response.text)

            return response.json()

        raise SportlogiqError(response.status_code, response.url, response.text)


class Resource:
    """Base for endpoint groups. Holds the shared transport."""

    def __init__(self, transport: Transport) -> None:
        self._t = transport
