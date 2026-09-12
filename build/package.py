"""Build the shippable zip, end to end.

    python build/package.py            # build, stage and zip
    python build/package.py --no-build # re-stage and zip an existing build

Produces dist/RapheBoardFlasher_v<version>.zip containing the two executables,
the operator README, the PC check script, and empty firmware/ and logs/ folders.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
DIST = ROOT / "dist"
STAGE = DIST / "RapheBoardFlasher"
EXTRAS = ROOT / "build" / "package"

sys.path.insert(0, str(SRC))
from rprm_flasher import __version__  # noqa: E402

#: Everything that must exist in the staged folder before it is worth zipping.
REQUIRED = [
    "RapheBoardFlasher.exe",
    "rprm-flasher.exe",
    "README.txt",
    "Check-This-PC-First.cmd",
    "_internal/rprm_flasher/backends/avr/tools/avrdude.exe",
    "_internal/rprm_flasher/backends/avr/tools/avrdude.conf",
    "_internal/rprm_flasher/backends/avr/tools/LICENSE.txt",
    "_internal/rprm_flasher/config/boards/avr.json",
    "_internal/rprm_flasher/ui/assets/logo.png",
    "_internal/rprm_flasher/ui/assets/fonts/BebasNeue-Regular.ttf",
    "_internal/rprm_flasher/ui/assets/fonts/Poppins-SemiBold.ttf",
]


def build() -> None:
    print("building with PyInstaller...")
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(ROOT / "build/flasher.spec"),
         "--noconfirm", "--distpath", str(DIST),
         "--workpath", str(DIST / ".work")],
        check=True,
        cwd=ROOT,
    )


def stage() -> None:
    for name in ("README.txt", "Check-This-PC-First.cmd"):
        shutil.copy2(EXTRAS / name, STAGE / name)
    for folder in ("firmware", "logs"):
        (STAGE / folder).mkdir(exist_ok=True)
    # Git does not carry empty folders and neither does zip; a placeholder
    # keeps them in the delivered package.
    (STAGE / "firmware" / "put-firmware-files-here.txt").write_text(
        "Any .hex or .bin file in this folder appears in the program's\n"
        "'From library' list. A manifest.json alongside them can give each a\n"
        "readable name.\n",
        encoding="utf-8",
    )
    (STAGE / "logs" / "reports-appear-here.txt").write_text(
        "The program writes its reports here. Email one of these if you get\n"
        "stuck - it contains everything needed to work out what happened.\n",
        encoding="utf-8",
    )


def verify() -> list[str]:
    return [name for name in REQUIRED if not (STAGE / name).exists()]


def zip_up() -> Path:
    # Not Path.with_suffix: on "..._v1.0.0" it would replace the ".0".
    target = DIST / f"RapheBoardFlasher_v{__version__}.zip"
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in sorted(STAGE.rglob("*")):
            if item.is_file():
                archive.write(item, Path(STAGE.name) / item.relative_to(STAGE))
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-build", action="store_true",
                        help="skip PyInstaller and package what is already there")
    args = parser.parse_args()

    if not args.no_build:
        build()
    if not STAGE.is_dir():
        print(f"nothing staged at {STAGE}", file=sys.stderr)
        return 1

    stage()
    missing = verify()
    if missing:
        print("package is incomplete:", file=sys.stderr)
        for name in missing:
            print(f"  missing {name}", file=sys.stderr)
        return 1

    archive = zip_up()
    folder_mb = sum(f.stat().st_size for f in STAGE.rglob("*") if f.is_file()) / 1048576
    print(f"\nfolder  {folder_mb:6.1f} MB  {STAGE}")
    print(f"zip     {archive.stat().st_size / 1048576:6.1f} MB  {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
