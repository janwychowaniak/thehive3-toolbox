# thehive3-toolbox

`th3tb` is a small command-line toolbox for administrators of **TheHive 3.x** and
**Cortex 2.x**, the Elasticsearch-based generation of both applications. It talks
to their REST APIs only, and for now it only reads: nothing it does changes the
state of an instance.

TheHive and Cortex are handled separately, each with its own settings, so the
toolbox works just as well against a partial stack (TheHive without Cortex, or
the other way round).

## Compatibility

- TheHive 3.3 and 3.4: only API routes that already exist in TheHive 3.3 are used
- Cortex 2.1
- Python 3.8 or newer, with [requests](https://requests.readthedocs.io/) as the
  only dependency

Tested against TheHive 3.4.0 and Cortex 2.1.3, with requests 2.22 and 2.32.

## Installation

```sh
git clone https://github.com/janwychowaniak/thehive3-toolbox.git
cd thehive3-toolbox
pip install .
th3tb --help
```

No installation is needed on hosts where `requests` is already available (for
example from the system's `python3-requests` package). Run it straight from the
clone instead:

```sh
cd thehive3-toolbox
python3 -m thehive3_toolbox --help
```

## Configuration

Settings come from environment variables, one set per application:

| TheHive             | Cortex                | Meaning                                    |
|---------------------|-----------------------|--------------------------------------------|
| `TH3TB_HIVE_URL`    | `TH3TB_CORTEX_URL`    | base URL of the application (required)     |
| `TH3TB_HIVE_KEY`    | `TH3TB_CORTEX_KEY`    | API key (needed by every command but `status`) |
| `TH3TB_HIVE_VERIFY` | `TH3TB_CORTEX_VERIFY` | TLS certificate verification (optional)    |

```sh
export TH3TB_HIVE_URL=https://thehive.example.com
export TH3TB_HIVE_KEY=<api-key>
```

### TLS certificate verification

The `*_VERIFY` variables only matter for `https://` URLs:

- **unset**: the default verification of requests
- **a path** to a CA bundle (a PEM file, or a directory prepared with `c_rehash`):
  verify against that CA, typically a private one
- **`false`**: no verification at all (for labs with self-signed certificates);
  `th3tb` prints a warning on every run

Mind where your requests comes from. Installed with pip, it trusts only the CA
list bundled in the `certifi` package, not the system's trust store, so a private
CA installed system-wide stays invisible to it. Distribution packages (Debian's
and Ubuntu's `python3-requests`, for example) are patched to use the system store
instead. Either way, pointing `*_VERIFY` at the CA works. requests' own
`REQUESTS_CA_BUNDLE` variable is honoured too and applies to both applications,
but `*_VERIFY` takes precedence.

## Commands

```
th3tb hive   status | whoami | users  [--json]
th3tb hive   cases | alerts | observables | tasks  [filters] [--limit N] [--count] [--json]
th3tb hive   case NUMBER|ID  [--json]
th3tb hive   stats  [--newer-than AGE] [--older-than AGE] [--top N] [--json]
th3tb hive   audit  [filters] [--limit N] [--count] [--json]
th3tb hive   alert ID  [--json]
th3tb hive   templates | custom-fields | data-types | report-templates  [--json]
th3tb hive   export
th3tb cortex status | whoami | users  [--json]
th3tb cortex analyzers | responders  [--show-config] [--json]
```

| Command  | What it shows | Needs |
|----------|---------------|-------|
| `status` | version, health of the components, authentication methods | no API key |
| `whoami` | the user behind the configured API key and its roles | any valid key |
| `users`  | users with their roles, status and whether they have an API key | TheHive: any valid key; Cortex: `orgadmin` (own organization) or `superadmin` (all organizations) |
| `cases` | TheHive only: cases matching `--status`, `--resolution`, `--tag`, `--owner`, `--older-than`, `--newer-than` and `--title`, newest first | any valid key |
| `case` | TheHive only: one case, by its number (as in the GUI) or id, with custom fields, metrics, tasks and observables | any valid key |
| `alerts` | TheHive only: alerts matching `--status`, `--tag`, `--source`, `--type`, `--older-than`, `--newer-than` and `--title`, newest first | any valid key |
| `alert` | TheHive only: one alert, by id, with its observables and linked case | any valid key |
| `observables` | TheHive only: observables of all cases matching `--value` (exact; for files, a hash of the file), `--type`, `--ioc`, `--tag`, `--older-than` and `--newer-than`, newest first, with their case | any valid key |
| `tasks` | TheHive only: tasks of all cases matching `--status` (Waiting and InProgress by default), `--owner`, `--title`, `--older-than` and `--newer-than`, newest first, with their case | any valid key |
| `stats` | TheHive only: counts of cases and alerts created in a time window (the last 30 days by default), by status, resolution, severity, owner, tag, source and type, and per day, week or month | any valid key |
| `audit` | TheHive only: who created, updated or deleted what, newest first, by `--user`, `--operation`, `--object-type`, `--object`, `--case` and age; the last 7 days unless the history of one case or object is asked for | any valid key |
| `templates` | TheHive only: case templates and what they preset (severity, TLP, PAP, tasks, custom fields, metrics) | any valid key |
| `custom-fields` | TheHive only: definitions of custom fields | any valid key |
| `data-types` | TheHive only: observable data types, the defaults told from those added locally | any valid key |
| `report-templates` | TheHive only: report templates of Cortex analyzers | any valid key; the Cortex connector enabled |
| `export` | TheHive only: all of the above plus case metrics as one JSON document | any valid key |
| `analyzers`, `responders` | Cortex only: workers enabled in the key's organization and the state of their definitions; with `--show-config` also their full configuration | any valid key; checking definitions needs `orgadmin` or `superadmin`; `--show-config` needs `orgadmin` |

```
$ th3tb hive status
TheHive           3.4.0-1
URL               https://thehive.example.com
Status            WARNING
Elasticsearch     WARNING
Connector cortex  OK
  cortex1         OK (version 2.1.3-1)
Auth methods      key, local
ZIP password      malware

$ th3tb hive users
LOGIN       NAME           ROLES               STATUS  API KEY
alice       Alice Example  read, write, admin  Ok      no
bob         Bob Example    read, write         Locked  no
svc-alerts  Alert feed     read, write, alert  Ok      yes

$ th3tb hive cases --tag phishing --older-than 90d --limit 3
3 of 1284 cases, newest first
NUMBER  CREATED           STATUS                   SEVERITY  TLP    OWNER  TITLE
#40211  2025-06-30 14:02  Resolved: FalsePositive  medium    AMBER  alice  Suspicious invoice from example.com
#40187  2025-06-29 09:41  Open                     high      AMBER  bob    Credential phishing wave
#40102  2025-06-27 17:15  Resolved: TruePositive   medium    GREEN  alice  Reported mail with a link to 192.0.2.10

$ th3tb hive observables --value 192.0.2.44
3 of 3 observables, newest first
CREATED           TYPE  VALUE       IOC  CASE              CASE TITLE
2025-06-30 14:05  ip    192.0.2.44  yes  #40211            Suspicious invoice from example.com
2025-05-12 08:20  ip    192.0.2.44  no   #39870            Outbound traffic to a rare host
2024-11-03 21:47  ip    192.0.2.44  no   #35102 (Deleted)  Scanner noise

$ th3tb hive templates
NAME      TITLE PREFIX  SEVERITY  TLP    PAP    TASKS  CUSTOM FIELDS  METRICS
Malware   -             high      RED    GREEN  0      0              0
Phishing  [PHISH]       medium    AMBER  AMBER  2      1              1

$ th3tb hive data-types
16 data types, 2 of them added locally; default ones removed: regexp
DATA TYPE          ORIGIN
autonomous-system  default
...
iban               local
...
wallet             local

$ th3tb cortex users
Users of organization analysts (orgadmin sees only its own)
ORGANIZATION  LOGIN        NAME                 ROLES                    STATUS  API KEY  PASSWORD
analysts      carol        Carol Example        read, analyze, orgadmin  Ok      no       yes
analysts      svc-thehive  TheHive integration  read, analyze            Ok      yes      no

$ th3tb cortex analyzers
Analyzers enabled in organization lab: 4
NAME           VERSION  STATE
DnsLookup_1_0  1.0      ok
GeoIp_2_0      2.0      definition missing (3.1 available)
Retired_1_0    -        definition missing
Sandbox_1_0    1.0      update available (1.2)
```

`--json` prints the same data as JSON. Notes and warnings go to stderr, so
stdout can be piped (for example to `jq`).

Tables cut values longer than 60 characters short; `--json` always has them in
full.

`users` never reads the API keys themselves, only whether a user has one. In
Cortex, a key without a password usually marks an integration account.

`analyzers` and `responders` compare each enabled worker with the catalog of
definitions Cortex currently knows. Updating that catalog usually replaces a
definition with a newer version, and workers still enabled on the old one stop
working: they show up as `definition missing`, together with the version to
enable instead.

With `--show-config` they also print each worker's full configuration: every
value Cortex passes to the worker when it runs, including the TLP/PAP limits,
proxies and, in clear text, the API keys of third-party services. Values other
than plain strings are shown as JSON, so `true`, `null` and `""` stay
distinguishable. Cortex returns configurations only to users with the
`orgadmin` role, which a superadmin never holds, so the option needs such a key.
Without it, configurations are left out.

```
$ th3tb cortex analyzers --show-config
Analyzers enabled in organization lab: 1
NAME       VERSION  STATE
GeoIp_2_0  2.0      ok

GeoIp_2_0
  check_tlp   true
  key         <api-key>
  max_tlp     2
  proxy_http  null
```

### Searching large instances

These commands query the same Elasticsearch the instance runs on, so they are
built to stay cheap even on indices holding millions of cases:

- Filters become term, terms, range and match queries only, all answered from
  the inverted index. Wildcard and `query_string` queries, which can scan whole
  fields, are never generated: `--title` matches whole words (every one of them
  must occur), not substrings.
- A listing asks for at most `--limit` results, sorted newest first: 100 by
  default, 10 000 at most. Up to 100 (twice elastic4play's default
  `search.pagesize`), TheHive answers with one plain search, which walks the
  matching documents once: with no filters at all that means every case, alert,
  observable or task of the instance, as on the GUI's search pages, and filters
  make it cheaper.
- Beyond 100, TheHive reads the results through a scroll in batches of ten, and
  in Elasticsearch 5 every batch of a sorted scroll walks the whole match set
  again. So a larger `--limit` first counts the matches and is served only when
  at most 10 000 match; otherwise the command stops and asks for narrower
  filters, for example time windows with `--older-than` and `--newer-than`. A
  match set of at most 100 still gets one plain search.
- `--count` fetches a single result without sorting and reads the total from the
  `X-Total` header (elastic4play turns an empty range such as `0-0` into ten
  results, so that is no cheaper).
- A listing makes no follow-up request per result. `observables` and `tasks` add
  one ids query for the cases of the whole page. Only `case` fetches tasks and
  observables, the same queries the GUI makes when opening a case: a plain search
  for up to 100 of each, and a larger one only for cases that have more, up to
  1000.
- Cases with status `Deleted` (TheHive's soft delete, hidden in the GUI) are left
  out unless asked for with `--status Deleted`; deleted observables never show.
  Observables and tasks of a soft-deleted case are listed with `(Deleted)` next to
  its number, and those whose case is gone altogether with `(missing)`.
- `--value` is an exact, case-sensitive match on the observable's value, or on
  any hash TheHive keeps for a file observable (SHA-256, SHA-1 and MD5 by
  default). Observables inside alerts are not searched.

Ages are given as `30d`, `12w`, `2y` or a date `YYYY-MM-DD`, and apply to the
creation time. Times are shown and dates read in local time.

The resolution of a resolved case (`TruePositive`, `FalsePositive`,
`Indeterminate`, `Other`, `Duplicated`) shows in the STATUS column and can be
filtered on with `--resolution`. Its impact (`impactStatus`) is in the `--json`
output.

### Statistics

`th3tb hive stats` counts the cases (soft-deleted ones left out) and alerts
created in a time window: the last 30 days by default, or any other window given
with `--newer-than` and `--older-than` (with only `--older-than`, the 30 days
before it). Cases are broken down by status, resolution, severity, owner and tag,
alerts by status, source and type, both also per day, week or month depending on
the length of the window. For fields that hold one value per document, the
documents outside the top rows are summed up as `(other or none)`.

```
$ th3tb hive stats --top 3
Created between 2025-08-31 09:00 and 2025-09-30 09:00

CASES: 412 (soft-deleted ones left out)

STATUS    COUNT
Resolved  371
Open      41

RESOLUTION       COUNT
FalsePositive    198
TruePositive     121
Other            52
(other or none)  41

OWNER            COUNT
alice            140
bob              131
carol            97
(other or none)  44

...

DAY (UTC)   COUNT
2025-09-01  17     ###############################
2025-09-02  22     ########################################
2025-09-03  15     ###########################
2025-09-04  0
...
```

Each breakdown is one terms aggregation, and each timeline one date histogram,
over the documents of the window only: TheHive's `_stats` merges the buckets of
several aggregations into one flat object, so they are requested one by one.
Scripted aggregations are never used. Periods are calendar days, weeks (from
Monday) or months in UTC, as Elasticsearch aligns them, and empty ones at both
ends of the window are filled in. With many shards, the top values of fields
holding many different values (owners, tags, sources, types) are approximate,
as usual with Elasticsearch terms aggregations.

### Audit trail

`th3tb hive audit` lists TheHive's audit entries: who (`--user`) created,
updated or deleted (`--operation`) which object (`--object-type`, `--object`),
and when, with the attributes the entry records. `--case` shows the whole history
of one case and everything in it (tasks, logs, observables, analyzer jobs), by
number or id.

Audit entries are the most numerous documents of an instance, so a listing
without its own start (`--newer-than`) keeps to the last 7 days; the history of
one case or object is shown whole. Everything else works as for the other
listings, `--limit`, `--count` and the limit on large match sets included.

```
$ th3tb hive audit --case 40211
4 of 4 audit entries, newest first
TIME              USER        OPERATION  OBJECT         OBJECT ID                         CASE    CHANGES
2025-07-02 10:14  alice       Update     case           AYdE2kqFbT1x0p9QwZrA              #40211  resolutionStatus=FalsePositive, status=Resolved, summary=Legitimate invoice
2025-06-30 14:20  alice       Update     case_task      AYdE2mNFbT1x0p9QwZrD              #40211  owner=alice, status=InProgress
2025-06-30 14:05  svc-alerts  Creation   case_artifact  5f2b8c0e9a7d4e61b3c2a1f0d9e8c7b6  #40211  dataType=ip, ioc=true, message=Sender IP
2025-06-30 14:02  svc-alerts  Creation   case           AYdE2kqFbT1x0p9QwZrA              #40211  severity=2, status=Open, title=Suspicious invoice from exa..., tlp=2
```

The CHANGES column leaves out empty values and internal fields; `--json` has
every attribute of every entry.

### Comparing and backing up TheHive configuration

`th3tb hive export` prints the case templates (tasks included), custom field
definitions, case metrics, observable data types and report templates (HTML
content included) as one JSON document. Fields that differ between instances by
nature (ids, creation and update times, authors) are left out and everything is
sorted, so two exports differ only where the configuration really does:

```sh
TH3TB_HIVE_URL=https://thehive-a.example.com th3tb hive export > a.json
TH3TB_HIVE_URL=https://thehive-b.example.com th3tb hive export > b.json
diff a.json b.json
```

The same works over time, to see what changed on one instance. Case metrics are
TheHive 3's numeric per-case values, which the GUI asks for when a case is
closed; they only appear in the export.

### Exit status

| Code | Meaning |
|------|---------|
| 0 | success |
| 1 | `status`: the application answers, but a component reports WARNING |
| 2 | `status`: a component reports ERROR; any command: the request failed |

This follows the usual monitoring-plugin convention, so `th3tb hive status` can
serve as a health check. A single-node Elasticsearch whose indices have replicas
is permanently yellow, which TheHive reports as WARNING.

## Notes on the APIs

- TheHive's `/api/health` never answers `Ok` once any connector (such as Cortex)
  is configured, because it does not deduplicate the statuses it compares.
  `status` therefore derives the health from the components listed by
  `/api/status`.
- The `ElasticSearch` version in TheHive's `/api/status` is the client library
  bundled with TheHive, not the version of the cluster. Cortex reports both.
- Cortex 2 does not implement `/api/health` (it answers 501) and reports no
  component health, so for Cortex `status` only checks that the application
  answers.
- Every request authenticated with an API key makes TheHive read through all
  active users with a scroll, to find the one holding the key: the key field
  cannot be searched. The cost grows with the number of users, not with the size
  of the index, and every API-key integration pays it; unauthenticated requests
  (`status`) do not.
- The ZIP password is the one TheHive uses to wrap downloaded attachments
  (`datastore.attachment.password`, `malware` by default). The GUI shows it next
  to every download, so it is not a secret.

## Development

Secret scanning with [gitleaks](https://github.com/gitleaks/gitleaks) runs in CI
and in local git hooks. Enable the hooks once per clone:

```sh
git config core.hooksPath .githooks
```

Unit tests use only the standard library:

```sh
python3 -m unittest discover -s tests
```

## License

MIT
