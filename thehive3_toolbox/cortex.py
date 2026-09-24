"""Cortex 2.x commands."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from . import ToolboxError, output
from .client import Client

COMMANDS = [
    ("status", "version of Cortex and of its Elasticsearch cluster (no API key needed)"),
    ("whoami", "the user behind the configured API key"),
    ("users", "users with their roles, status and whether they have an API key"),
    ("analyzers", "enabled analyzers and the state of their definitions"),
    ("responders", "enabled responders and the state of their definitions"),
]


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


def cmd_analyzers(client: Client, as_json: bool) -> int:
    return _workers(client, as_json, "analyzer")


def cmd_responders(client: Client, as_json: bool) -> int:
    return _workers(client, as_json, "responder")


def _workers(client: Client, as_json: bool, kind: str) -> int:
    # Enabled workers are listed per organization, to any user; the catalog of
    # available definitions needs orgadmin or superadmin. As an orgadmin the
    # listing also carries each worker's configuration, API keys of third-party
    # services included; assess_workers() picks its fields explicitly, so none of
    # it is ever shown.
    me = client.get("/api/user/current")
    workers = client.get(f"/api/{kind}", params={"range": "all"})
    definitions = None
    if {"orgadmin", "superadmin"} & set(me.get("roles", [])):
        definitions = client.get(f"/api/{kind}definition")
    records = assess_workers(workers, definitions)

    output.note(f"{kind.capitalize()}s enabled in organization {me.get('organization')}: "
                f"{len(records)}")
    if definitions is None:
        output.note("Checking definitions needs the orgadmin or superadmin role; "
                    "states not checked.")
    if as_json:
        output.print_json(records)
    else:
        output.print_table(["NAME", "VERSION", "STATE"],
                           [[r["name"], r["version"], _state_text(r)] for r in records])
    return 0


def assess_workers(workers: List[Dict[str, Any]],
                   definitions: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Match enabled workers against the catalog of worker definitions.

    A worker points to its definition by id, which Cortex builds as
    "<name>_<version>" with dots turned into underscores. Updating the catalog
    usually replaces a definition with a newer version, which leaves workers
    enabled on the old one pointing to nothing: they stop working until the new
    version is enabled. With definitions=None (catalog not readable) the states
    stay unknown.
    """
    newest: Dict[str, Dict[str, Any]] = {}
    for definition in definitions or []:
        known = newest.get(definition["name"])
        if known is None or _version_key(definition["version"]) > _version_key(known["version"]):
            newest[definition["name"]] = definition
    catalog = {d["id"]: d for d in definitions or []}

    records = []
    for worker in sorted(workers, key=lambda w: w.get("name") or ""):
        definition_id = worker.get("workerDefinitionId")
        record = {
            "name": worker.get("name"),
            "definition_id": definition_id,
            "version": worker.get("version"),
            "state": None,  # ok, update_available or definition_missing
            "available_version": None,
            "data_types": worker.get("dataTypeList", []),
        }
        if definitions is not None:
            definition = catalog.get(definition_id)
            if definition is not None:
                name, version = definition["name"], definition["version"]
            else:
                name, version = _split_definition_id(definition_id or "", newest)
            record["version"] = version
            latest = newest.get(name) if name else None
            if definition is None:
                record["state"] = "definition_missing"
            elif latest and _version_key(latest["version"]) > _version_key(version):
                record["state"] = "update_available"
            else:
                record["state"] = "ok"
            if record["state"] != "ok" and latest:
                record["available_version"] = latest["version"]
        records.append(record)
    return records


def _split_definition_id(definition_id: str,
                         names: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Name and version of a definition id whose definition is gone, as far as a
    name still in the catalog allows telling them apart."""
    matches = [n for n in names
               if definition_id.startswith(n + "_")
               and re.fullmatch(r"\d[\w-]*", definition_id[len(n) + 1:])]
    if not matches:
        return None, None
    name = max(matches, key=len)
    return name, definition_id[len(name) + 1:].replace("_", ".")


def _version_key(version: Optional[str]) -> Tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version or ""))


def _state_text(record: Dict[str, Any]) -> str:
    state, available = record["state"], record["available_version"]
    if state == "update_available":
        return f"update available ({available})"
    if state == "definition_missing":
        return f"definition missing ({available} available)" if available else "definition missing"
    return state or "-"
