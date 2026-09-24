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
th3tb cortex status | whoami | users  [--json]
th3tb cortex analyzers | responders  [--show-config] [--json]
```

| Command  | What it shows | Needs |
|----------|---------------|-------|
| `status` | version, health of the components, authentication methods | no API key |
| `whoami` | the user behind the configured API key and its roles | any valid key |
| `users`  | users with their roles, status and whether they have an API key | TheHive: any valid key; Cortex: `orgadmin` (own organization) or `superadmin` (all organizations) |
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
