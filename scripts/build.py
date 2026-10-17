"""Build an OS-native portable distribution without cross-platform claims."""

from __future__ import annotations

import argparse
import hashlib
from importlib import import_module
from importlib.metadata import distribution
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def collect_notices(app_dir: Path, license_cache: Path | None = None) -> None:
    """Retain the license files and license metadata shipped in build wheels."""
    shared = import_module(f"{__package__}.windows_portable" if __package__ else "windows_portable")
    cache = license_cache or ROOT / "build" / "license-cache"
    cache.mkdir(parents=True, exist_ok=True)
    shared.copy_licenses(app_dir, cache)
    notices = [
        "Seoyoung POS - bundled third-party components",
        "",
        "Python: https://docs.python.org/3/license.html",
        "SQLite: public domain - https://www.sqlite.org/copyright.html",
        "Qt/PySide6 license information: https://doc.qt.io/qtforpython-6/licenses.html",
        "Qt LGPLv3/GPLv3 and openpyxl/et_xmlfile MIT texts accompany this distribution.",
        "Qt upstream source: https://download.qt.io/archive/qt/6.8/6.8.3/submodules/",
        "PySide upstream source: https://code.qt.io/cgit/pyside/pyside-setup.git/",
        "Qt libraries remain replaceable separate files in _internal.",
        "This application does not restrict reverse engineering of or replacing LGPL libraries.",
        "",
    ]
    for package in (
        "PySide6", "PySide6-Essentials", "PySide6-Addons", "shiboken6",
        "openpyxl", "et-xmlfile", "pyinstaller",
    ):
        installed = distribution(package)
        metadata = installed.metadata
        notices.extend([
            f"{metadata['Name']} {installed.version}",
            f"License: {metadata.get('License-Expression') or metadata.get('License') or 'See package metadata'}",
            "",
        ])
        for file in installed.files or ():
            if "license" not in str(file).lower() and "copying" not in str(file).lower():
                continue
            source = Path(installed.locate_file(file))
            if source.is_file():
                target = app_dir / "licenses" / package / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    for name in ("LICENSE.txt", "LICENSE"):
        source = Path(sys.base_prefix) / name
        if source.is_file():
            target = app_dir / "licenses" / "Python" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    notice_text = "\n".join(notices)
    (app_dir / "THIRD_PARTY_NOTICES.txt").write_text(notice_text, encoding="utf-8")
    (app_dir / "licenses" / "THIRD-PARTY-NOTICES.txt").write_text(notice_text, encoding="utf-8")


def write_archive(destination: Path, archive: Path) -> Path:
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                bundle.write(path, Path(destination.name) / path.relative_to(destination))
    with zipfile.ZipFile(archive) as bundle:
        bad = bundle.testzip()
        if bad:
            raise RuntimeError(f"Archive integrity failure: {bad}")
        print(f"Archive integrity: {len(bundle.infolist())} files, CRC check passed", flush=True)
    with archive.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    checksum_file = archive.with_suffix(archive.suffix + ".sha256")
    checksum_file.write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    print(f"Portable archive: {archive}", flush=True)
    print(f"SHA256: {checksum}", flush=True)
    return archive


def build(*, native: bool = False, verify: bool = True, license_cache: Path | None = None) -> Path:
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Build with Python 3.12 (the tested runtime).")
    if struct.calcsize("P") != 8:
        raise SystemExit("A 64-bit Python installation is required.")
    if sys.platform != "win32" and not native:
        raise SystemExit(
            "Windows EXEs must be built on Windows. Use build_windows.bat or the "
            "Windows build workflow. --native builds only for this host OS."
        )

    target = "Windows" if sys.platform == "win32" else platform.system()
    architecture = "x64" if platform.machine().lower() in {"amd64", "x86_64"} else platform.machine()
    dist = ROOT / "dist"
    work_parent = ROOT / "build"
    dist.mkdir(exist_ok=True)
    work_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pos-build-", dir=work_parent) as temp:
        scratch = Path(temp)
        output = scratch / "dist"
        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--name",
            "SeoyoungPOS",
            "--distpath",
            str(output),
            "--workpath",
            str(scratch / "work"),
            "--specpath",
            str(scratch),
            "--paths",
            str(ROOT),
            "--hidden-import",
            "openpyxl",
        ]
        if sys.platform == "win32":
            command.append("--windowed")
        command.append(str(ROOT / "run.py"))
        build_env = dict(os.environ)
        build_env["PYINSTALLER_CONFIG_DIR"] = str(scratch / "cache")
        run(command, env=build_env)

        app_dir = output / "SeoyoungPOS"
        executable = app_dir / ("SeoyoungPOS.exe" if sys.platform == "win32" else "SeoyoungPOS")
        if not executable.is_file():
            raise SystemExit(f"Build did not produce the expected executable: {executable}")
        if verify:
            smoke_env = dict(os.environ)
            smoke_env["QT_QPA_PLATFORM"] = "offscreen"
            run([str(executable), "--demo", "--smoke-test"], env=smoke_env)
        shutil.copy2(ROOT / "README.md", app_dir / "README.md")
        for name in ("windows-portable-notes.md", "VALIDATION.md"):
            document = ROOT / "docs" / name
            if document.is_file():
                (app_dir / "docs").mkdir(exist_ok=True)
                shutil.copy2(document, app_dir / "docs" / document.name)
        collect_notices(app_dir, license_cache)

        destination = dist / "SeoyoungPOS"
        if destination.exists():
            # Only replace this script's generated application output. Business
            # data is never copied into or deleted from a prior portable folder.
            previous_data = destination / "data"
            if previous_data.exists():
                raise SystemExit(
                    f"Existing portable business data found at {previous_data}. "
                    "Move the old application folder aside before rebuilding."
                )
            retired = dist / "SeoyoungPOS.previous"
            if retired.exists():
                raise SystemExit(f"Move {retired} aside before rebuilding again.")
            destination.rename(retired)
        shutil.move(str(app_dir), destination)
        archive = dist / f"SeoyoungPOS-{target}-{architecture}-portable.zip"
        return write_archive(destination, archive)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--native",
        action="store_true",
        help="Build for the current OS, including Linux; this does not create a Windows EXE.",
    )
    parser.add_argument("--license-cache", type=Path, help="Reusable cache for hash-verified upstream license texts.")
    args = parser.parse_args()
    build(native=args.native, license_cache=args.license_cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
