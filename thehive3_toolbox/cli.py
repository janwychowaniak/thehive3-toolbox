"""th3tb: the command-line entry point."""

from __future__ import annotations

import argparse
from typing import List, Optional

from . import ToolboxError, __version__, cortex, hive, output
from .client import Client
from .config import env_name, load

# Each application module lists its commands in COMMANDS and implements them as
# cmd_<name>(client, args) -> exit status. An optional add_arguments(command,
# parser) hook adds command-specific options.
APPS = {
    "hive": (hive, "TheHive 3.x"),
    "cortex": (cortex, "Cortex 2.x"),
}

EPILOG = """\
configuration (environment variables, set per application):
  TH3TB_HIVE_URL     TH3TB_CORTEX_URL      base URL, e.g. https://thehive.example.com
  TH3TB_HIVE_KEY     TH3TB_CORTEX_KEY      API key
  TH3TB_HIVE_VERIFY  TH3TB_CORTEX_VERIFY   TLS verification: unset (default),
                                           a CA bundle path, or "false"

exit status:
  0  success
  1  status: the application answers, but a component reports WARNING
  2  status: a component reports ERROR; any command: the request failed
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="th3tb",
        description="Command-line toolbox for administrators of TheHive 3.x and Cortex 2.x.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="print JSON instead of text")

    apps = parser.add_subparsers(dest="app", metavar="APP", required=True)
    for app, (module, title) in APPS.items():
        app_parser = apps.add_parser(app, help=f"commands for {title}",
                                     description=f"Commands for {title}.")
        commands = app_parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
        add_arguments = getattr(module, "add_arguments", None)
        for name, help_text in module.COMMANDS:
            command = commands.add_parser(name, parents=[common], help=help_text,
                                          description=help_text[0].upper() + help_text[1:] + ".")
            if add_arguments:
                add_arguments(name, command)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    module = APPS[args.app][0]
    try:
        config = load(args.app)
        if config.verify is False and config.url.startswith("https://"):
            output.note(f"th3tb: warning: TLS certificate verification is disabled "
                        f"({env_name(args.app, 'VERIFY')})")
        return getattr(module, f"cmd_{args.command}")(Client(config), args)
    except ToolboxError as exc:
        output.note(f"th3tb: error: {exc}")
        return 2
    except KeyboardInterrupt:
        return 130
