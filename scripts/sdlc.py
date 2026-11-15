"""agentic-sdlc runner entry: python3 <plugin root>/scripts/sdlc.py <command> ...

Puts its own directory first on sys.path so `sdlc_runner` always resolves to the package shipped
next to this file, then hands over to `sdlc_runner.cli.main`.
"""
import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)


def main() -> int:
    if not sys.path or sys.path[0] != _HERE:
        sys.path.insert(0, _HERE)
    try:
        from sdlc_runner.cli import main as cli_main
    except ModuleNotFoundError as exc:
        if exc.name != "sdlc_runner.cli":
            raise  # a missing module inside the CLI is a real error, not an unbuilt one
        print("error=cli_not_built")
        return 2
    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
