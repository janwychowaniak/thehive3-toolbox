"""Thin HTTP client shared by the TheHive and Cortex commands."""

from __future__ import annotations

import re
from typing import Any, Optional

import requests
import urllib3

from . import ToolboxError, __version__
from .config import AppConfig, ConfigError, env_name

TIMEOUT = 30  # seconds, per request


class ApiError(ToolboxError):
    """The application could not be reached or refused the request."""


class Client:
    def __init__(self, config: AppConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers["User-Agent"] = f"thehive3-toolbox/{__version__}"
        if config.verify is False:
            # The CLI warns once per run; urllib3 would warn on every request.
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def get(self, path: str, *, auth: bool = True, params: Optional[dict] = None) -> Any:
        return self._request("GET", path, auth=auth, params=params)

    def post(self, path: str, body: Any, *, params: Optional[dict] = None) -> Any:
        return self._request("POST", path, auth=True, params=params, body=body)

    def _request(self, method: str, path: str, *, auth: bool,
                 params: Optional[dict] = None, body: Any = None) -> Any:
        url = self.config.url + path
        headers = {}
        if auth:
            if not self.config.key:
                raise ConfigError(f"{env_name(self.config.app, 'KEY')} is not set "
                                  "(this command needs an API key)")
            headers["Authorization"] = f"Bearer {self.config.key}"
        try:
            resp = self.session.request(method, url, params=params, json=body, headers=headers,
                                        verify=self.config.verify, timeout=TIMEOUT)
        # SSLError and ConnectTimeout are both ConnectionErrors, so the order matters.
        except requests.exceptions.SSLError as exc:
            reason = _ssl_reason(exc)
            hint = ""
            if "certificate verify failed" in reason:
                hint = (f"\nIf the server uses a private CA, point "
                        f"{env_name(self.config.app, 'VERIFY')} at its certificate bundle.")
            raise ApiError(f"TLS error for {url}: {reason}{hint}")
        except requests.exceptions.Timeout:
            raise ApiError(f"no response from {url} within {TIMEOUT} s")
        except requests.exceptions.ConnectionError:
            raise ApiError(f"cannot connect to {url}")
        except requests.exceptions.RequestException as exc:
            raise ApiError(f"request to {url} failed: {exc}")

        if resp.status_code == 401:
            raise ApiError(f"authentication failed (HTTP 401): check "
                           f"{env_name(self.config.app, 'KEY')}")
        if resp.status_code == 403:
            raise ApiError("permission denied (HTTP 403): the key's user lacks "
                           "the role this command needs")
        if not resp.ok:
            raise ApiError(f"HTTP {resp.status_code} from {method} {path}: {_brief(resp)}")
        try:
            return resp.json()
        except ValueError:
            raise ApiError(f"{method} {path} did not return JSON; is {url} really "
                           "the application's base URL?")


def _ssl_reason(exc: Exception) -> str:
    """The OpenSSL reason buried in urllib3's retry wrapper, e.g. "certificate
    verify failed: self-signed certificate"; the full text when it is not found."""
    match = re.search(r"\[SSL[^\]]*\]\s*([^('\"]+)", str(exc))
    return match.group(1).strip() if match else str(exc)


def _brief(resp: requests.Response) -> str:
    """The error message of a TheHive/Cortex error body, or the start of the raw text."""
    try:
        message = resp.json().get("message")
    except (ValueError, AttributeError):
        message = None
    if message:
        return message
    raw = " ".join(resp.text.split())
    return (raw[:200] + "...") if len(raw) > 200 else (raw or resp.reason)
