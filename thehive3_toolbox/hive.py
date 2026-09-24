"""TheHive 3.x commands. Only API routes that already exist in TheHive 3.3 are used."""

from __future__ import annotations

import argparse
import datetime
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

from . import ToolboxError, output
from .client import MAX_RESULTS, ApiError, Client

COMMANDS = [
    ("status", "version and health of TheHive and its connectors (no API key needed)"),
    ("whoami", "the user behind the configured API key"),
    ("users", "users with their roles, status and whether they have an API key"),
    ("cases", "cases matching the filters, newest first"),
    ("case", "one case with its custom fields, tasks and observables"),
    ("alerts", "alerts matching the filters, newest first"),
    ("alert", "one alert with its observables"),
    ("observables", "observables of all cases matching the filters, newest first, with their case"),
    ("tasks", "tasks of all cases matching the filters, newest first, with their case"),
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


# --- Cases and alerts ----------------------------------------------------------
#
# Every query here is built from term, terms, range and match clauses only: all
# of them resolve through the inverted index. Wildcard and query_string clauses,
# which can scan whole fields of a large index, are never generated. A listing is
# one search of at most MAX_RESULTS results; --count asks for a single one.

CASE_STATUSES = ["Open", "Resolved", "Deleted"]
ALERT_STATUSES = ["New", "Updated", "Ignored", "Imported"]
TASK_STATUSES = ["Waiting", "InProgress", "Completed", "Cancel"]
RESOLUTIONS = ["TruePositive", "FalsePositive", "Indeterminate", "Other", "Duplicated"]
DEFAULT_LIMIT = 100  # up to here elastic4play answers with one plain search
DETAIL_CAP = 1000  # tasks or observables shown for one case
_AGE = re.compile(r"(\d+)([dwy])")
_AGE_DAYS = {"d": 1, "w": 7, "y": 365}


def add_arguments(command: str, parser: argparse.ArgumentParser) -> None:
    if command == "cases":
        parser.add_argument("--status", action="append", choices=CASE_STATUSES,
                            help="only this status (repeatable); by default Deleted cases are left out")
        parser.add_argument("--resolution", action="append", choices=RESOLUTIONS,
                            help="only resolved cases with this resolution (repeatable)")
        parser.add_argument("--owner", metavar="LOGIN", help="only cases owned by this user")
    elif command == "alerts":
        parser.add_argument("--status", action="append", choices=ALERT_STATUSES,
                            help="only this status (repeatable)")
        parser.add_argument("--source", help="only alerts from this source")
        parser.add_argument("--type", help="only alerts of this type")
    elif command == "observables":
        parser.add_argument("--value", help="only this exact value; for files, a hash of the file")
        parser.add_argument("--type", metavar="DATA_TYPE", help="only this data type")
        parser.add_argument("--ioc", action="store_true", help="only observables flagged as IOC")
    elif command == "tasks":
        parser.add_argument("--status", action="append", choices=TASK_STATUSES,
                            help="only this status (repeatable); by default Waiting and InProgress")
        parser.add_argument("--owner", metavar="LOGIN", help="only tasks assigned to this user")
    elif command == "case":
        parser.add_argument("ref", metavar="NUMBER|ID",
                            help="case number as shown in the GUI (with or without #), or case id")
    elif command == "alert":
        parser.add_argument("alert_id", metavar="ID", help="alert id, as listed by alerts")

    if command in ("cases", "alerts", "observables", "tasks"):
        if command != "tasks":
            parser.add_argument("--tag", action="append",
                                help="only with this tag (repeatable: all must match)")
        if command != "observables":
            parser.add_argument("--title", metavar="WORDS", help="every word must occur in the title")
        parser.add_argument("--older-than", type=_cutoff, metavar="AGE",
                            help="created before: 30d, 12w, 2y or a date YYYY-MM-DD")
        parser.add_argument("--newer-than", type=_cutoff, metavar="AGE",
                            help="created after: 30d, 12w, 2y or a date YYYY-MM-DD")
        parser.add_argument("--limit", type=_limit, default=DEFAULT_LIMIT,
                            help=f"how many to show, newest first (default {DEFAULT_LIMIT}, "
                                 f"at most {MAX_RESULTS})")
        parser.add_argument("--count", action="store_true", help="only print how many match")


def cmd_cases(client: Client, args: argparse.Namespace) -> int:
    clauses = [_in("status", args.status or ["Open", "Resolved"])] + _filters(args)
    if args.resolution:
        clauses.append(_in("resolutionStatus", args.resolution))
    if args.owner:
        clauses.append({"owner": args.owner})
    return _listing(client, args, "/api/case/_search", clauses, "cases",
                    ["NUMBER", "CREATED", "STATUS", "SEVERITY", "TLP", "OWNER", "TITLE"],
                    lambda c, _: [f"#{c.get('caseId')}", _when(c.get("createdAt")), _case_status(c),
                               _SEVERITY.get(c.get("severity"), c.get("severity")),
                               _TLP.get(c.get("tlp"), c.get("tlp")), c.get("owner"), c.get("title")])


def cmd_alerts(client: Client, args: argparse.Namespace) -> int:
    clauses = _filters(args)
    if args.status:
        clauses.append(_in("status", args.status))
    for field in ("source", "type"):
        if getattr(args, field):
            clauses.append({field: getattr(args, field)})
    return _listing(client, args, "/api/alert/_search", clauses, "alerts",
                    ["ID", "CREATED", "STATUS", "SEVERITY", "SOURCE", "TYPE", "SOURCE REF", "TITLE"],
                    lambda a, _: [a.get("id"), _when(a.get("createdAt")), a.get("status"),
                               _SEVERITY.get(a.get("severity"), a.get("severity")), a.get("source"),
                               a.get("type"), a.get("sourceRef"), a.get("title")])


def cmd_observables(client: Client, args: argparse.Namespace) -> int:
    # Deleted observables stay in the index with status Deleted; the GUI hides them.
    clauses = [{"status": "Ok"}] + _filters(args)
    if args.value:
        clauses.append({"_or": [{"data": args.value}, {"attachment.hashes": args.value}]})
    if args.type:
        clauses.append({"dataType": args.type})
    if args.ioc:
        clauses.append({"ioc": True})
    return _listing(client, args, "/api/case/artifact/_search", clauses, "observables",
                    ["CREATED", "TYPE", "VALUE", "IOC", "CASE", "CASE TITLE"],
                    lambda o, case: [_when(o.get("createdAt")), o.get("dataType"), _observable_value(o),
                                     bool(o.get("ioc")), _case_number(case, o), (case or {}).get("title")],
                    with_case=True)


def cmd_tasks(client: Client, args: argparse.Namespace) -> int:
    clauses = [_in("status", args.status or ["Waiting", "InProgress"])] + _filters(args)
    if args.owner:
        clauses.append({"owner": args.owner})
    return _listing(client, args, "/api/case/task/_search", clauses, "tasks",
                    ["CREATED", "STATUS", "OWNER", "TASK", "CASE", "CASE TITLE"],
                    lambda t, case: [_when(t.get("createdAt")), t.get("status"), t.get("owner"),
                                     t.get("title"), _case_number(case, t), (case or {}).get("title")],
                    with_case=True)


def cmd_case(client: Client, args: argparse.Namespace) -> int:
    case = _find_case(client, args.ref)
    case_path = f"/api/case/{quote(case['id'], safe='')}"
    tasks, tasks_total = _fetch_all(client, f"{case_path}/task/_search")
    # Deleted observables stay in the index with status Deleted; the GUI hides them.
    observables, observables_total = _fetch_all(client, f"{case_path}/artifact/_search",
                                                {"status": "Ok"})
    tasks.sort(key=lambda t: (t.get("group") or "", t.get("order") or 0, t.get("title") or ""))
    observables.sort(key=lambda o: (o.get("dataType") or "", _observable_value(o) or ""))
    if args.json:
        output.print_json({"case": _no_meta(case), "tasks": [_no_meta(t) for t in tasks],
                           "observables": [_no_meta(o) for o in observables]})
        return 0

    output.print_fields([
        ("Case", f"#{case.get('caseId')}  {case.get('title')}"),
        ("Id", case.get("id")),
        ("Status", _case_status(case)),
        ("Severity", _SEVERITY.get(case.get("severity"), case.get("severity"))),
        ("TLP / PAP", f"{_TLP.get(case.get('tlp'), case.get('tlp'))} / "
                      f"{_TLP.get(case.get('pap'), case.get('pap'))}"),
        ("Owner", case.get("owner")),
        ("Created", f"{_when(case.get('createdAt'))} by {output.text(case.get('createdBy'))}"),
        ("Started", _when(case.get("startDate"))),
        ("Ended", _when(case.get("endDate"))),
        ("Tags", case.get("tags")),
    ] + [(f"Custom field {ref}", _custom_field_value(value))
         for ref, value in sorted((case.get("customFields") or {}).items())]
      + [(f"Metric {name}", value) for name, value in sorted((case.get("metrics") or {}).items())])
    for label, key in (("Description", "description"), ("Summary", "summary")):
        if case.get(key):
            print(f"\n{label}:")
            print("\n".join("  " + line for line in case[key].splitlines()))

    print(f"\nTasks ({_shown(len(tasks), tasks_total)}):")
    output.print_table(["GROUP", "TITLE", "STATUS", "OWNER"],
                       [[t.get("group"), t.get("title"), t.get("status"), t.get("owner")] for t in tasks])
    print(f"\nObservables ({_shown(len(observables), observables_total)}):")
    output.print_table(["TYPE", "VALUE", "IOC", "TAGS"],
                       [[o.get("dataType"), _observable_value(o), bool(o.get("ioc")), o.get("tags")]
                        for o in observables])
    return 0


def cmd_alert(client: Client, args: argparse.Namespace) -> int:
    alert = _get_or_none(client, f"/api/alert/{quote(args.alert_id, safe='')}")
    if alert is None:
        raise ToolboxError(f"no alert with id {args.alert_id}")
    case = _get_or_none(client, f"/api/case/{quote(alert['case'], safe='')}") if alert.get("case") else None
    artifacts = sorted(alert.get("artifacts") or [],
                       key=lambda o: (o.get("dataType") or "", _observable_value(o) or ""))
    if args.json:
        output.print_json(_no_meta(alert))
        return 0

    linked = None
    if alert.get("case"):
        linked = f"#{case.get('caseId')}  {case.get('title')}" if case else f"{alert['case']} (not found)"
    output.print_fields([
        ("Alert", alert.get("title")),
        ("Id", alert.get("id")),
        ("Status", alert.get("status")),
        ("Severity", _SEVERITY.get(alert.get("severity"), alert.get("severity"))),
        ("TLP", _TLP.get(alert.get("tlp"), alert.get("tlp"))),
        ("Source", f"{output.text(alert.get('source'))} / {output.text(alert.get('type'))} / "
                   f"{output.text(alert.get('sourceRef'))}"),
        ("Date", _when(alert.get("date"))),
        ("Created", _when(alert.get("createdAt"))),
        ("Case template", alert.get("caseTemplate")),
        ("Case", linked),
        ("Tags", alert.get("tags")),
    ])
    if alert.get("description"):
        print("\nDescription:")
        print("\n".join("  " + line for line in alert["description"].splitlines()))
    print(f"\nObservables ({len(artifacts)}):")
    output.print_table(["TYPE", "VALUE", "IOC", "TAGS"],
                       [[o.get("dataType"), _observable_value(o), bool(o.get("ioc")), o.get("tags")]
                        for o in artifacts])
    return 0


def _listing(client: Client, args: argparse.Namespace, path: str, clauses: List[Dict[str, Any]],
             noun: str, headers: List[str],
             row: Callable[[Dict[str, Any], Optional[Dict[str, Any]]], List[Any]],
             with_case: bool = False) -> int:
    """List one page of results; with_case also looks up, in a single search, the
    cases the listed tasks or observables belong to."""
    query = {"_and": clauses} if clauses else None
    if args.count:
        # One result and no sorting: the total comes from the X-Total header.
        _, total = client.search(path, query, limit=1)
        if args.json:
            output.print_json({"count": total})
        else:
            print(total)
        return 0
    limit = args.limit
    if limit > DEFAULT_LIMIT:
        # Past DEFAULT_LIMIT elastic4play reads through a scroll in batches of ten,
        # and in Elasticsearch 5 every batch of a sorted scroll walks the whole set
        # of matching documents again. Large pages are therefore served only for
        # match sets of bounded size, counted first.
        _, total = client.search(path, query, limit=1)
        if total > MAX_RESULTS:
            raise ToolboxError(
                f"{total} {noun} match; more than {DEFAULT_LIMIT} results are listed only when at "
                f"most {MAX_RESULTS} match. Narrow the filters down (for example into time windows "
                f"with --newer-than and --older-than) or keep --limit at {DEFAULT_LIMIT} or below.")
        limit = max(1, min(limit, total))  # a small set still gets one plain search
    items, total = client.search(path, query, limit=limit, sort="-createdAt")
    cases = _parent_cases(client, items) if with_case else {}
    output.note(f"{len(items)} of {total} {noun}, newest first")
    if args.json:
        output.print_json([dict(_no_meta(i), case=_case_summary(cases.get(i.get("_parent")), i))
                           if with_case else _no_meta(i) for i in items])
    else:
        output.print_table(headers, [row(i, cases.get(i.get("_parent"))) for i in items])
    return 0


def _parent_cases(client: Client, items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The cases of listed tasks or observables, fetched with one ids query."""
    ids = sorted({i["_parent"] for i in items if i.get("_parent")})
    if not ids:
        return {}
    found, _ = client.search("/api/case/_search", _in("_id", ids), limit=len(ids))
    return {c["id"]: c for c in found}


def _case_number(case: Optional[Dict[str, Any]], child: Dict[str, Any]) -> str:
    if case is None:
        # A task or observable whose case is gone altogether (not just soft-deleted).
        return f"{child.get('_parent')} (missing)"
    deleted = " (Deleted)" if case.get("status") == "Deleted" else ""
    return f"#{case.get('caseId')}{deleted}"


def _case_summary(case: Optional[Dict[str, Any]], child: Dict[str, Any]) -> Dict[str, Any]:
    if case is None:
        return {"id": child.get("_parent"), "missing": True}
    return {"id": case.get("id"), "number": case.get("caseId"), "title": case.get("title"),
            "status": case.get("status")}


def _filters(args: argparse.Namespace) -> List[Dict[str, Any]]:
    """Clauses of the options every listing shares (tags and title where offered)."""
    clauses: List[Dict[str, Any]] = [{"tags": tag} for tag in getattr(args, "tag", None) or []]
    if args.older_than is not None:
        clauses.append({"_lt": {"createdAt": args.older_than}})
    if args.newer_than is not None:
        clauses.append({"_gt": {"createdAt": args.newer_than}})
    # One match clause per word, so that all of them must occur.
    title = getattr(args, "title", None) or ""
    clauses += [{"_like": {"_field": "title", "_value": word}} for word in title.split()]
    return clauses


def _in(field: str, values: List[str]) -> Dict[str, Any]:
    return {"_in": {"_field": field, "_values": values}}


def _find_case(client: Client, ref: str) -> Dict[str, Any]:
    ref = ref.lstrip("#")
    if ref.isdigit():
        found, _ = client.search("/api/case/_search", {"caseId": int(ref)}, limit=1)
        if not found:
            raise ToolboxError(f"no case #{ref}")
        return found[0]
    case = _get_or_none(client, f"/api/case/{quote(ref, safe='')}")
    if case is None:
        raise ToolboxError(f"no case with id {ref}")
    return case


def _get_or_none(client: Client, path: str) -> Optional[Dict[str, Any]]:
    try:
        return client.get(path)
    except ApiError as exc:
        if exc.status == 404:
            return None
        raise


def _fetch_all(client: Client, path: str,
               query: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], int]:
    """Up to DETAIL_CAP children of one case: a plain search, and a larger one
    (read through a scroll) only when the case has more."""
    items, total = client.search(path, query, limit=DEFAULT_LIMIT)
    if total > len(items):
        items, total = client.search(path, query, limit=min(total, DETAIL_CAP))
    return items, total


def _case_status(case: Dict[str, Any]) -> str:
    status = case.get("status") or "-"
    resolution = case.get("resolutionStatus")
    return f"{status}: {resolution}" if status == "Resolved" and resolution else status


def _custom_field_value(value: Any) -> Any:
    """A case's custom field is stored as {"order": n, "<type>": value}."""
    if isinstance(value, dict):
        values = [v for k, v in value.items() if k != "order"]
        return values[0] if values else None
    return value


def _observable_value(observable: Dict[str, Any]) -> Optional[str]:
    attachment = observable.get("attachment") or {}
    return observable.get("data") or attachment.get("name")


def _shown(shown: int, total: int) -> str:
    return f"{total}" if shown >= total else f"{shown} of {total}"


def _when(millis: Any) -> Optional[str]:
    if not isinstance(millis, (int, float)):
        return None
    return datetime.datetime.fromtimestamp(millis / 1000).strftime("%Y-%m-%d %H:%M")


def _no_meta(entity: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def _cutoff(value: str) -> int:
    """An age (30d, 12w, 2y) or a date (YYYY-MM-DD, local time) as epoch milliseconds."""
    match = _AGE.fullmatch(value)
    if match:
        days = int(match.group(1)) * _AGE_DAYS[match.group(2)]
        return int((time.time() - days * 86400) * 1000)
    try:
        return int(datetime.datetime.strptime(value, "%Y-%m-%d").timestamp() * 1000)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected an age such as 30d, 12w or 2y, or a date YYYY-MM-DD, got {value!r}")


def _limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError:
        limit = 0
    if not 1 <= limit <= MAX_RESULTS:
        raise argparse.ArgumentTypeError(
            f"expected 1 to {MAX_RESULTS} (narrow larger sets down with filters), got {value!r}")
    return limit
