"""Cortex 2.x commands."""

from __future__ import annotations

from typing import Any, Dict
from urllib.parse import quote

from . import ToolboxError, output
from .client import Client


def cmd_status(client: Client, as_json: bool) -> int:
    # Cortex 2 reports no component health (its /api/health is not implemented and
    # answers 501), so a successful /api/status is all there is to check.
    status = client.get("/api/status", auth=False)
    versions = status.get("versions", {})
    auth = status.get("config", {}).get("authType", [])
    data = {
        "url": client.config.url,
        "version": versions.get("Cortex"),
        "status": "OK",
        "elasticsearch_version": versions.get("ElasticSearch cluster"),
        "auth_methods": auth if isinstance(auth, list) else [auth],
        "libraries": {"elastic4play": versions.get("Elastic4Play"),
                      "elasticsearch_client": versions.get("ElasticSearch client")},
    }
    if as_json:
        output.print_json(data)
    else:
        output.print_fields([
            ("Cortex", data["version"]),
            ("URL", data["url"]),
            ("Status", "OK (reachable; Cortex 2 reports no component health)"),
            ("Elasticsearch", data["elasticsearch_version"]),
            ("Auth methods", data["auth_methods"]),
        ])
    return 0


def cmd_whoami(client: Client, as_json: bool) -> int:
    user = _user(client.get("/api/user/current"))
    if as_json:
        output.print_json(user)
    else:
        output.print_fields([
            ("Login", user["login"]),
            ("Name", user["name"]),
            ("Organization", user["organization"]),
            ("Roles", user["roles"]),
            ("Status", user["status"]),
        ])
    return 0


def cmd_users(client: Client, as_json: bool) -> int:
    # What a key may list depends on its user: superadmin sees every organization,
    # orgadmin only its own, anyone else nothing.
    me = client.get("/api/user/current")
    roles = me.get("roles", [])
    if "superadmin" in roles:
        path, scope = "/api/user/_search", "all organizations"
    elif "orgadmin" in roles:
        organization = me.get("organization") or ""
        path = f"/api/organization/{quote(organization, safe='')}/user/_search"
        scope = f"organization {organization} (orgadmin sees only its own)"
    else:
        raise ToolboxError(f"listing users needs the orgadmin or superadmin role; "
                           f"user {me.get('id')} has: {output.text(roles)}")
    found = client.post(path, {}, params={"range": "all"})
    users = sorted((_user(u) for u in found),
                   key=lambda u: (u["organization"] or "", u["login"] or ""))
    output.note(f"Users of {scope}")
    if as_json:
        output.print_json(users)
    else:
        output.print_table(
            ["ORGANIZATION", "LOGIN", "NAME", "ROLES", "STATUS", "API KEY", "PASSWORD"],
            [[u["organization"], u["login"], u["name"], u["roles"], u["status"],
              u["has_key"], u["has_password"]] for u in users])
    return 0


def _user(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "login": raw.get("id"),
        "name": raw.get("name"),
        "organization": raw.get("organization"),
        "roles": raw.get("roles", []),  # read, analyze, orgadmin, superadmin
        "status": raw.get("status"),    # Ok or Locked
        "has_key": raw.get("hasKey", False),
        # A key without a password usually marks an integration account.
        "has_password": raw.get("hasPassword", False),
    }
