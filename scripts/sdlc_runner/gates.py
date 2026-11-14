"""Gates, questions and notes (contract §11). STUB until plan Task 7 replaces this module.

`register_cli` registers `approve`, `reject`, `ask`, `answer` and `note`; each handler raises
SdlcError(2, "not_built:<command>") whatever arguments it gets (`accepts_extra`: cli.py passes
unknown arguments through instead of refusing them as a usage error). The engine already reads
what Task 7 will write: approve records in approvals.jsonl (checks.check_approval) and a pending
question in state.waiting.
"""
from __future__ import annotations

from .textio import SdlcError

COMMANDS = ("approve", "reject", "ask", "answer", "note")


def _handler(name):
    def not_built(*_args, **_kwargs):
        raise SdlcError(2, "not_built:" + name)
    return not_built


def register_cli(subparsers) -> None:
    for name in COMMANDS:
        parser = subparsers.add_parser(name, help="%s (not built yet: plan Task 7)" % name)
        parser.set_defaults(handler=_handler(name), accepts_extra=True)
