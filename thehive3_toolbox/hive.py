"""TheHive 3.x commands. Only API routes that already exist in TheHive 3.3 are used."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List, Optional

from . import ToolboxError, output
from .client import ApiError, Client

COMMANDS = [
    ("status", "version and health of TheHive and its connectors (no API key needed)"),
    ("whoami", "the user behind the configured API key"),
    ("users", "users with their roles, status and whether they have an API key"),
    ("templates", "case templates and what they preset"),
    ("custom-fields", "definitions of custom fields"),
    ("data-types", "observable data types, the default ones told from those added locally"),
    ("report-templates", "report templates of Cortex analyzers (needs the Cortex connector)"),
    ("export", "all of the configuration above, case metrics included, as one JSON "
               "document for backups and diffs"),
]
JSON_ONLY = {"export"}

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


# --- Configuration -------------------------------------------------------------

# Present in a fresh TheHive 3.3 / 3.4 (Migration.scala, addDataTypes).
DEFAULT_DATA_TYPES = {
    "autonomous-system", "domain", "file", "filename", "fqdn", "hash", "ip", "mail",
    "mail_subject", "other", "regexp", "registry", "uri_path", "url", "user-agent",
}
_SEVERITY = {1: "low", 2: "medium", 3: "high"}
_TLP = {0: "WHITE", 1: "GREEN", 2: "AMBER", 3: "RED"}  # PAP uses the same scale
# Fields that differ between instances by nature; left out so that diffs show
# only real configuration differences.
_VOLATILE = {"id", "createdAt", "createdBy", "updatedAt", "updatedBy"}


def cmd_templates(client: Client, args: argparse.Namespace) -> int:
    templates = _templates(client)
    if args.json:
        output.print_json(templates)
    else:
        output.print_table(
            ["NAME", "TITLE PREFIX", "SEVERITY", "TLP", "PAP", "TASKS", "CUSTOM FIELDS", "METRICS"],
            [[t.get("name"), t.get("titlePrefix"), _SEVERITY.get(t.get("severity"), t.get("severity")),
              _TLP.get(t.get("tlp"), t.get("tlp")), _TLP.get(t.get("pap"), t.get("pap")),
              len(t.get("tasks") or []), len(t.get("customFields") or {}), len(t.get("metrics") or {})]
             for t in templates])
    return 0


def cmd_custom_fields(client: Client, args: argparse.Namespace) -> int:
    fields = _custom_fields(client)
    if args.json:
        output.print_json(fields)
    else:
        output.print_table(
            ["REFERENCE", "NAME", "TYPE", "MANDATORY", "OPTIONS", "DESCRIPTION"],
            [[f.get("reference"), f.get("name"), f.get("type"), bool(f.get("mandatory")),
              f.get("options"), f.get("description")] for f in fields])
    return 0


def cmd_data_types(client: Client, args: argparse.Namespace) -> int:
    data_types = _data_types(client)
    local = [t for t in data_types if t not in DEFAULT_DATA_TYPES]
    removed = sorted(DEFAULT_DATA_TYPES - set(data_types))
    output.note(f"{len(data_types)} data types, {len(local)} of them added locally"
                + (f"; default ones removed: {', '.join(removed)}" if removed else ""))
    if args.json:
        output.print_json([{"data_type": t, "default": t in DEFAULT_DATA_TYPES} for t in data_types])
    else:
        output.print_table(["DATA TYPE", "ORIGIN"],
                           [[t, "default" if t in DEFAULT_DATA_TYPES else "local"] for t in data_types])
    return 0


def cmd_report_templates(client: Client, args: argparse.Namespace) -> int:
    templates = _report_templates(client)
    if templates is None:
        raise ToolboxError("this TheHive has no Cortex connector enabled, which is where "
                           "report templates live")
    if args.json:
        output.print_json(templates)
    else:
        output.print_table(["ANALYZER", "TYPE", "SIZE"],
                           [[t.get("analyzerId"), t.get("reportType"), len(t.get("content") or "")]
                            for t in templates])
    return 0


def cmd_export(client: Client, args: argparse.Namespace) -> int:
    report_templates = _report_templates(client)
    if report_templates is None:
        output.note("No Cortex connector enabled: report templates left out.")
    output.print_json({
        "thehive": {"url": client.config.url,
                    "version": client.get("/api/status", auth=False).get("versions", {}).get("TheHive")},
        "case_templates": _templates(client),
        "custom_fields": _custom_fields(client),
        "case_metrics": sorted(_dblist(client, "case_metrics"), key=lambda m: m.get("name") or ""),
        "observable_data_types": _data_types(client),
        "report_templates": report_templates,
    }, sort_keys=True)
    return 0


def _templates(client: Client) -> List[Dict[str, Any]]:
    # Deleting a case template is a real delete, so every one found is live.
    found = client.post("/api/case/template/_search", {}, params={"range": "all"})
    return sorted((_clean(t) for t in found), key=lambda t: t.get("name") or "")


def _custom_fields(client: Client) -> List[Dict[str, Any]]:
    return sorted(_dblist(client, "custom_fields"), key=lambda f: f.get("reference") or "")


def _data_types(client: Client) -> List[str]:
    return sorted(_dblist(client, "list_artifactDataType"))


def _report_templates(client: Client) -> Optional[List[Dict[str, Any]]]:
    """Report templates, or None when TheHive has no Cortex connector."""
    try:
        found = client.post("/api/connector/cortex/report/template/_search", {},
                            params={"range": "all"})
    except ApiError as exc:
        if exc.status == 404:
            return None
        raise
    return sorted((_clean(t) for t in found),
                  key=lambda t: (t.get("analyzerId") or "", t.get("reportType") or ""))


def _dblist(client: Client, name: str) -> List[Any]:
    """Values of a TheHive list; the item ids, random per instance, are dropped."""
    return list(client.get(f"/api/list/{name}").values())


def _clean(entity: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in entity.items() if not k.startswith("_") and k not in _VOLATILE}
