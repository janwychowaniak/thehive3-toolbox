"""Thin HTTP client shared by the TheHive and Cortex commands."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

import requests
import urllib3

from . import ToolboxError, __version__
from .config import AppConfig, ConfigError, env_name

TIMEOUT = 30  # seconds, per request
# elastic4play serves a search as one plain Elasticsearch query up to twice its
# search.pagesize (50 by default); anything larger switches to a scroll, which
# holds a context open on the cluster. One page is kept within that bound.
MAX_PAGE = 100


class ApiError(ToolboxError):
    """The application could not be reached or refused the request."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status  # HTTP status code, if the application answered


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

    def search(self, path: str, query: Optional[dict] = None, *, limit: int, offset: int = 0,
               sort: Optional[str] = None) -> Tuple[List[Any], int]:
        """One page of an elastic4play search and the total number of hits.

        elastic4play reads the page as range=<from>-<to>; note that it turns an
        empty range such as 0-0 into its default of 10 results.
        """
        if not 1 <= limit <= MAX_PAGE:
            raise ValueError(f"page size {limit} out of 1..{MAX_PAGE}")
        params = {"range": f"{offset}-{offset + limit}"}
        if sort:
            params["sort"] = sort
        resp = self._send("POST", path, auth=True, params=params,
                          body={"query": query} if query else {})
        items = self._json(resp, "POST", path)
        return items, int(resp.headers.get("X-Total", len(items)))

    def _request(self, method: str, path: str, *, auth: bool,
                 params: Optional[dict] = None, body: Any = None) -> Any:
        return self._json(self._send(method, path, auth=auth, params=params, body=body),
                          method, path)

    def _send(self, method: str, path: str, *, auth: bool,
              params: Optional[dict] = None, body: Any = None) -> requests.Response:
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
                           f"{env_name(self.config.app, 'KEY')}", 401)
        if resp.status_code == 403:
            raise ApiError("permission denied (HTTP 403): the key's user lacks "
                           "the role this command needs", 403)
        if not resp.ok:
            raise ApiError(f"HTTP {resp.status_code} from {method} {path}: {_brief(resp)}",
                           resp.status_code)
        return resp

    def _json(self, resp: requests.Response, method: str, path: str) -> Any:
        try:
            return resp.json()
        except ValueError:
            raise ApiError(f"{method} {path} did not return JSON; is {self.config.url} "
                           "really the application's base URL?")


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
