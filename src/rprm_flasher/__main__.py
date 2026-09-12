"""Single entry point for both faces of the tool.

No arguments opens the window; any argument runs the command line. That lets one
build produce two executables - a windowed one an operator double-clicks, and a
console one for diagnostics - from the same code, with no duplicated logic.

    python -m rprm_flasher                 # the GUI
    python -m rprm_flasher selftest        # the CLI
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)

    # Absolute imports, deliberately: PyInstaller runs this file as a top-level
    # script rather than as part of the package, so a relative import fails with
    # "attempted relative import with no known parent package" in the frozen
    # build while working perfectly from source.
    if args:
        from rprm_flasher.cli import main as cli_main

        return cli_main(args)

    from rprm_flasher.app import main as gui_main

    return gui_main([sys.argv[0]])


if __name__ == "__main__":
    raise SystemExit(main())
