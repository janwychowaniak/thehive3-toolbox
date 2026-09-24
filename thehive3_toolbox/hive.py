"""TheHive 3.x commands. Only API routes that already exist in TheHive 3.3 are used."""

from __future__ import annotations

import argparse
from typing import Any, Dict

from . import output
from .client import Client

COMMANDS = [
    ("status", "version and health of TheHive and its connectors (no API key needed)"),
    ("whoami", "the user behind the configured API key"),
    ("users", "users with their roles, status and whether they have an API key"),
]

# /api/status reports Elasticsearch and connector health as OK / WARNING / ERROR.
# Anything else ("UNKNOWN", 3.4's "Init" right after start-up, a connector that has
# not been checked yet) counts as WARNING.
_LEVELS = ["OK", "WARNING", "ERROR"]
_EXIT = {"OK": 0, "WARNING": 1, "ERROR": 2}


def _level(value: Any) -> str:
    return value if value in _LEVELS else "WARNING"


def cmd_status(client: Client, args: argparse.Namespace) -> int:
    # Deliberately not /api/health: it never answers "Ok" once any connector is
    # configured (its list of statuses is not deduplicated), so the level is
    # derived from the components instead.
    status = client.get("/api/status", auth=False)
    versions = status.get("versions", {})
    config = status.get("config", {})
    auth = config.get("authType", [])
    connectors = []
    for name, connector in sorted(status.get("connectors", {}).items()):
        servers = connector.get("servers")
        connectors.append({
            "name": name,
            "status": connector.get("status"),
            # a failed check reports "servers" as an empty object, not a list
            "servers": [{"name": s.get("name"), "version": s.get("version"),
                         "status": s.get("status")}
                        for s in (servers if isinstance(servers, list) else [])],
        })
    es_health = status.get("health", {}).get("elasticsearch")
    level = max([_level(es_health)] + [_level(c["status"]) for c in connectors],
                key=_LEVELS.index)
    data = {
        "url": client.config.url,
        "version": versions.get("TheHive"),
        "status": level,
        "elasticsearch_health": es_health,
        "connectors": connectors,
        "auth_methods": auth if isinstance(auth, list) else [auth],
        # Shown next to every ZIP download in the GUI, so not a secret.
        "zip_password": config.get("protectDownloadsWith"),
        # "ElasticSearch" in /api/status is TheHive's bundled client library,
        # not the version of the cluster.
        "libraries": {"elastic4play": versions.get("Elastic4Play"),
                      "elasticsearch_client": versions.get("ElasticSearch")},
    }
    if args.json:
        output.print_json(data)
        return _EXIT[level]

    fields = [
        ("TheHive", data["version"]),
        ("URL", data["url"]),
        ("Status", level),
        ("Elasticsearch", es_health),
    ]
    for connector in connectors:
        fields.append((f"Connector {connector['name']}", connector["status"]))
        for server in connector["servers"]:
            fields.append((f"  {server['name']}",
                           f"{server['status']} (version {output.text(server['version'])})"))
    fields += [
        ("Auth methods", data["auth_methods"]),
        ("ZIP password", data["zip_password"]),
    ]
    output.print_fields(fields)
    return _EXIT[level]


def cmd_whoami(client: Client, args: argparse.Namespace) -> int:
    user = _user(client.get("/api/user/current"))
    if args.json:
        output.print_json(user)
    else:
        output.print_fields([
            ("Login", user["login"]),
            ("Name", user["name"]),
            ("Roles", user["roles"]),
            ("Status", user["status"]),
        ])
    return 0


def cmd_users(client: Client, args: argparse.Namespace) -> int:
    # Any user with the read role may list all users. The list is small, so it is
    # fetched in one go (range=all).
    found = client.post("/api/user/_search", {}, params={"range": "all"})
    users = sorted((_user(u) for u in found), key=lambda u: u["login"] or "")
    if args.json:
        output.print_json(users)
    else:
        output.print_table(
            ["LOGIN", "NAME", "ROLES", "STATUS", "API KEY"],
            [[u["login"], u["name"], u["roles"], u["status"], u["has_key"]] for u in users])
    return 0


def _user(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "login": raw.get("id"),
        "name": raw.get("name"),
        "roles": raw.get("roles", []),  # read, write, admin; alert marks integrations
        "status": raw.get("status"),    # Ok or Locked
        "has_key": raw.get("hasKey", False),
    }
