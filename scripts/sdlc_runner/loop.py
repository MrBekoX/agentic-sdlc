"""The runner-driven spec/plan loop (contract §10). STUB until plan Task 8 replaces this module.

`next_role` returns None, so the engine prints the draft step's own card; `register_cli`
registers `draft-check`, `loop-record` and `ingest-draft`, whose handlers raise
SdlcError(2, "not_built:<command>") whatever arguments they get (`accepts_extra`).
"""
from __future__ import annotations

from .textio import SdlcError

COMMANDS = ("draft-check", "loop-record", "ingest-draft")


def next_role(ctx, step, write: bool):
    """The role card of the loop step, or None (stub: the step's own card is printed)."""
    return None


def _handler(name):
    def not_built(*_args, **_kwargs):
        raise SdlcError(2, "not_built:" + name)
    return not_built


def register_cli(subparsers) -> None:
    for name in COMMANDS:
        parser = subparsers.add_parser(name, help="%s (not built yet: plan Task 8)" % name)
        parser.set_defaults(handler=_handler(name), accepts_extra=True)
