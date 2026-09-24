"""Per-application settings, read from environment variables.

Each application is configured on its own, so a partial stack (TheHive without
Cortex, or the other way round) needs no settings for the missing part:

    TH3TB_HIVE_URL      TH3TB_CORTEX_URL      base URL (required)
    TH3TB_HIVE_KEY      TH3TB_CORTEX_KEY      API key (for authenticated commands)
    TH3TB_HIVE_VERIFY   TH3TB_CORTEX_VERIFY   TLS verification (optional)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Union

from . import ToolboxError

_TRUE = {"", "1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class ConfigError(ToolboxError):
    """Missing or invalid configuration."""


@dataclass(frozen=True)
class AppConfig:
    app: str                           # "hive" or "cortex"
    url: str                           # without a trailing slash
    key: Optional[str]
    # None: requests' default verification (which also honours REQUESTS_CA_BUNDLE),
    # False: no verification, str: path to a CA bundle file or directory.
    verify: Union[None, bool, str]


def env_name(app: str, setting: str) -> str:
    return f"TH3TB_{app.upper()}_{setting}"


def load(app: str) -> AppConfig:
    url_var = env_name(app, "URL")
    url = os.environ.get(url_var, "").strip()
    if not url:
        raise ConfigError(f"{url_var} is not set")
    if not url.startswith(("http://", "https://")):
        raise ConfigError(f"{url_var} must start with http:// or https://, got {url!r}")
    key = os.environ.get(env_name(app, "KEY"), "").strip() or None
    return AppConfig(app=app, url=url.rstrip("/"), key=key, verify=_verify(app))


def _verify(app: str) -> Union[None, bool, str]:
    var = env_name(app, "VERIFY")
    raw = os.environ.get(var, "").strip()
    if raw.lower() in _TRUE:
        return None
    if raw.lower() in _FALSE:
        return False
    if not os.path.exists(raw):
        raise ConfigError(f"{var}: CA bundle not found: {raw}")
    return raw
