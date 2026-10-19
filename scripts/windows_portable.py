"""Assemble a Windows x64 portable app from verified upstream binaries.

This script can run on Linux, but does NOT execute or validate Windows code.
It uses the CPython-distributed NuGet runtime and distlib's relocatable GUI
launcher; it is deliberately separate from the native PyInstaller build.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import textwrap
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PYTHON_URL = "https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg"
PYTHON_CATALOG = "https://api.nuget.org/v3/catalog0/data/2025.04.08.14.01.15/python.3.12.10.json"
# Published by the Python Software Foundation on NuGet, catalog SHA512.
PYTHON_SHA512 = "u9pNz2iKlCEbYtUJaKkbOPMF0LjR7NkCafdKhvigpPzrt8oWKgdTpHaR6z3wyWQAm9PYGUxv0Zr66NX9AeHMDw=="
WHEELS = (
    ("PySide6", "6.8.3", "PySide6-6.8.3-cp39-abi3-win_amd64.whl", "722dc0061d8ef6dbb8c0b99864f21e83a5b49ece1ecb2d0b890840d969e1e461"),
    ("PySide6-Essentials", "6.8.3", "PySide6_Essentials-6.8.3-cp39-abi3-win_amd64.whl", "3c0fae5550aff69f2166f46476c36e0ef56ce73d84829eac4559770b0c034b07"),
    ("PySide6-Addons", "6.8.3", "PySide6_Addons-6.8.3-cp39-abi3-win_amd64.whl", "67548f6db11f4e1b7e4b6efd9c3fc2e8d275188a7b2feac388961128572a6955"),
    ("shiboken6", "6.8.3", "shiboken6-6.8.3-cp39-abi3-win_amd64.whl", "bca3a94513ce9242f7d4bbdca902072a1631888e0aa3a8711a52cc5dbe93588f"),
    ("openpyxl", "3.1.5", "openpyxl-3.1.5-py2.py3-none-any.whl", "5282c12b107bffeef825f4617dc029afaf41d0ea60823bbb665ef3079dc79de2"),
    ("et-xmlfile", "2.0.0", "et_xmlfile-2.0.0-py3-none-any.whl", "7a91720bc756843502c3b7504c77b8fe44217c85c537d85037f0f536151b2caa"),
    # Build-only: launcher and PE dependency inspection, not app dependencies.
    ("distlib", "0.4.0", "distlib-0.4.0-py2.py3-none-any.whl", "9659f7d87e46584a30b5780e43ac7a2143098441670ff0a49d5f9034c54a6c16"),
    ("pefile", "2024.8.26", "pefile-2024.8.26-py3-none-any.whl", "76f8b485dcd3b1bb8166f1128d395fa3d87af26360c2358fb75b80019b957c6f"),
)

LICENSE_INPUTS = (
    ("Qt-LGPL-3.0-only.txt", "https://raw.githubusercontent.com/qt/qtbase/v6.8.3/LICENSES/LGPL-3.0-only.txt", "da7eabb7bafdf7d3ae5e9f223aa5bdc1eece45ac569dc21b3b037520b4464768"),
    ("Qt-GPL-3.0-only.txt", "https://raw.githubusercontent.com/qt/qtbase/v6.8.3/LICENSES/GPL-3.0-only.txt", "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903"),
    ("openpyxl-3.1.5.tar.gz", "https://files.pythonhosted.org/packages/3d/f9/88d94a75de065ea32619465d2f77b29a0469500e99012523b91cc4141cd1/openpyxl-3.1.5.tar.gz", "cf0e3cf56142039133628b5acffe8ef0c12bc902d2aadd3e0fe5878dc08d1050"),
    ("et_xmlfile-2.0.0.tar.gz", "https://files.pythonhosted.org/packages/d3/38/af70d7ab1ae9d4da450eeec1fa3918940a5fafb9055e934af8d6eb0c2313/et_xmlfile-2.0.0.tar.gz", "dab3f4764309081ce75662649be815c4c9081e88f0837825f90fd28317d4da54"),
)

ENTRYPOINT = textwrap.dedent(r'''
    """Relocatable GUI entry point, executed after normal Python initialization."""
    from pathlib import Path
    import ctypes
    import sys
    import tempfile
    import traceback

    home = Path(sys.argv[0]).resolve().parent
    if not any(a == "--data-dir" or a.startswith("--data-dir=") for a in sys.argv[1:]) and not any(a in {"--demo", "--smoke-test"} for a in sys.argv[1:]):
        try:
            data = home / "data"
            data.mkdir(exist_ok=True)
            with tempfile.TemporaryFile(dir=data):
                pass
        except OSError:
            # Source-mode app chooses the OS per-user directory if omitted.
            pass
        else:
            sys.argv.extend(["--data-dir", str(data)])
    try:
        from seoyoung_pos.app import main
        result = main()
    except Exception:
        detail = traceback.format_exc()
        log = home / "startup-error.log"
        try:
            log.write_text(detail, encoding="utf-8")
        except OSError:
            pass
        ctypes.windll.user32.MessageBoxW(None, "서영 POS를 시작하지 못했습니다.\n폴더의 startup-error.log를 확인해 주세요.\n\n" + detail[-1800:], "서영 POS 실행 오류", 0x10)
        result = 1
    raise SystemExit(result or 0)
''').lstrip()


def read_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "SeoyoungPOS-portable-builder/1.0"})
    # Keep system TLS certificate and hostname verification enabled.
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def digest(path: Path, algorithm: str = "sha256") -> str:
    with path.open("rb") as stream:
        hasher = hashlib.new(algorithm)
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def download_verified(cache: Path, name: str, url: str, expected: str, algorithm: str, *, offline_cache: bool = False) -> Path:
    target = cache / name
    if not target.exists():
        if offline_cache:
            raise FileNotFoundError(f"Offline cache file missing: {target}; no network request was made")
        print(f"Downloading {name}", flush=True)
        payload = read_url(url)
        actual = hashlib.new(algorithm, payload).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Checksum mismatch for {name}; refusing the artifact")
        target.write_bytes(payload)
    if digest(target, algorithm) != expected:
        raise RuntimeError(f"Cached checksum mismatch for {target}; refusing the artifact")
    print(f"Verified {name} ({algorithm})", flush=True)
    return target


def upstream_artifacts(cache: Path, *, offline_cache: bool = False) -> tuple[Path, list[Path], list[dict]]:
    cache.mkdir(parents=True, exist_ok=True)
    wheels_dir = cache / "wheels"
    wheels_dir.mkdir(exist_ok=True)
    python_digest = base64.b64decode(PYTHON_SHA512).hex()
    runtime = download_verified(cache, "python.3.12.10.nupkg", PYTHON_URL, python_digest, "sha512", offline_cache=offline_cache)
    manifest = [{"name": "CPython", "version": "3.12.10", "url": PYTHON_URL, "catalog": PYTHON_CATALOG,
                 "filename": runtime.name, "sha512": python_digest, "catalog_packageHash": PYTHON_SHA512,
                 "verification_mode": "pinned_checksum_cache_only" if offline_cache else "pinned_checksum",
                 "integrity_reference": "embedded_nuget_catalog_sha512"}]
    wheels = []
    for package, version, filename, expected in WHEELS:
        metadata_url = f"https://pypi.org/pypi/{package}/{version}/json"
        item = {"name": package, "version": version, "filename": filename,
                "metadata": metadata_url, "sha256": expected, "metadata_fetched": not offline_cache}
        if offline_cache:
            # WHEELS records contain the digests verified during the original
            # trusted build. Never fetch metadata, infer a download URL, or
            # substitute a digest calculated from the local cached file.
            item["verification_mode"] = "pinned_checksum_cache_only"
            wheel = download_verified(wheels_dir, filename, metadata_url, expected, "sha256", offline_cache=True)
        else:
            metadata = json.loads(read_url(metadata_url))
            record = next(record for record in metadata["urls"] if record["filename"] == filename)
            if record["digests"]["sha256"] != expected:
                raise RuntimeError(f"Upstream checksum changed for {filename}; investigate before rebuilding")
            item.update(url=record["url"], verification_mode="pinned_checksum_and_upstream_metadata")
            wheel = download_verified(wheels_dir, filename, record["url"], expected, "sha256")
        wheels.append(wheel)
        manifest.append(item)
    return runtime, wheels, manifest


def unpack_archive(source: Path, destination: Path, *, prefix: str = "") -> None:
    with zipfile.ZipFile(source) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"Corrupt ZIP entry in {source.name}: {bad}")
        for entry in archive.infolist():
            if not entry.filename.startswith(prefix):
                continue
            relative = PurePosixPath(entry.filename[len(prefix):])
            if not relative.parts or relative.is_absolute() or ".." in relative.parts:
                if relative.parts:
                    raise RuntimeError(f"Unsafe ZIP path: {entry.filename}")
                continue
            target = destination.joinpath(*relative.parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as incoming, target.open("wb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)


def copy_source(destination: Path) -> dict[str, str]:
    package = ROOT / "seoyoung_pos"
    if not (package / "app.py").is_file():
        raise RuntimeError("App entry point seoyoung_pos/app.py does not yet exist")
    app = destination / "app" / "seoyoung_pos"
    app.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for source in sorted(package.rglob("*.py")):
        # Runtime package assets currently consist entirely of Python source.
        # Do not accidentally distribute a local database, .env or bytecode.
        if not source.is_file() or "__pycache__" in source.parts:
            continue
        relative = source.relative_to(package)
        target = app / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        hashes[str(relative)] = digest(target)
    if (ROOT / "README.md").is_file():
        shutil.copy2(ROOT / "README.md", destination / "README.md")
    for name in ("windows-portable-notes.md", "MANUAL_SCOPE.md", "VALIDATION.md", "RELEASE_NOTES.md"):
        document = ROOT / "docs" / name
        if document.is_file():
            (destination / "docs").mkdir(exist_ok=True)
            shutil.copy2(document, destination / "docs" / document.name)
    for screenshot in sorted((ROOT / "docs" / "screenshots").glob("*.png")):
        if screenshot.is_file():
            target = destination / "docs" / "screenshots" / screenshot.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(screenshot, target)
    return hashes


def create_launcher(destination: Path, distlib_wheel: Path) -> None:
    with zipfile.ZipFile(distlib_wheel) as archive:
        launcher = archive.read("distlib/w64.exe")
        license_name = next(name for name in archive.namelist() if name.endswith("/LICENSE.txt"))
        (destination / "licenses").mkdir(exist_ok=True)
        (destination / "licenses" / "distlib-LICENSE.txt").write_bytes(archive.read(license_name))
    if "<launcher_dir>\\".encode("utf-16-le") not in launcher:
        raise RuntimeError("distlib launcher does not support relocatable interpreter paths")
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("__main__.py", ENTRYPOINT)
    # Distlib resolves this supported prefix relative to its own .exe path.
    shebang = b'#!"<launcher_dir>\\runtime\\pythonw.exe"\n'
    (destination / "SeoyoungPOS.exe").write_bytes(launcher + shebang + payload.getvalue())


def copy_licenses(destination: Path, cache: Path, *, offline_cache: bool = False) -> list[dict]:
    licenses = destination / "licenses"
    licenses.mkdir(exist_ok=True)
    sources = []
    for filename, url, sha256 in LICENSE_INPUTS:
        source = download_verified(cache, filename, url, sha256, "sha256", offline_cache=offline_cache)
        if filename.endswith(".tar.gz"):
            # Wheel metadata declares MIT but omits its text. Preserve the
            # license from the exact, hash-verified upstream source release.
            with tarfile.open(source) as archive:
                member = next(item for item in archive.getmembers()
                              if PurePosixPath(item.name).name.lower() in {"licence.rst", "license.rst", "licence", "license", "licence.txt", "license.txt"})
                incoming = archive.extractfile(member)
                if incoming is None:
                    raise RuntimeError(f"License is not a regular file: {member.name}")
                (licenses / (filename.split("-")[0] + "-LICENSE.txt")).write_bytes(incoming.read())
        else:
            shutil.copy2(source, licenses / filename)
        sources.append({"filename": filename, "url": url, "sha256": sha256,
                        "verification_mode": "pinned_checksum_cache_only" if offline_cache else "pinned_checksum"})
    (licenses / "THIRD-PARTY-NOTICES.txt").write_text(
        "Seoyoung POS third-party components\n\n"
        "CPython 3.12.10: Python Software Foundation; see runtime/LICENSE.txt.\n"
        "Qt/PySide6/Shiboken 6.8.3: The Qt Company Ltd. and contributors.\n"
        "Core application bindings use LGPL v3; Qt-LGPL-3.0-only.txt and Qt-GPL-3.0-only.txt accompany this package.\n"
        "Qt/PySide libraries remain separate replaceable DLLs; this package contains unmodified upstream wheels.\n"
        "Corresponding upstream sources and module-specific third-party notices:\n"
        "  https://download.qt.io/archive/qt/6.8/6.8.3/submodules/\n"
        "  https://code.qt.io/cgit/qt/qtbase.git/?h=v6.8.3\n"
        "  https://code.qt.io/cgit/pyside/pyside-setup.git/\n"
        "  https://pypi.org/project/PySide6/6.8.3/\n"
        "Package license metadata and original notices are preserved in runtime/Lib/site-packages/*.dist-info/.\n"
        "openpyxl 3.1.5 and et_xmlfile 2.0.0: MIT; accompanying license texts extracted from upstream source releases.\n"
        "distlib 0.4.0 launcher: Python Software Foundation license; see distlib-LICENSE.txt.\n"
        "The source app and this builder do not restrict reverse engineering of LGPL libraries or replacing those libraries.\n",
        encoding="utf-8"
    )
    return sources


def validate_layout(destination: Path, pefile_wheel: Path) -> dict:
    sys.path.insert(0, str(pefile_wheel))
    import pefile

    required = ["SeoyoungPOS.exe", "runtime/python.exe", "runtime/pythonw.exe", "runtime/python312.dll",
                "runtime/DLLs/_sqlite3.pyd", "runtime/DLLs/sqlite3.dll", "runtime/Lib/sqlite3/__init__.py",
                "runtime/Lib/site-packages/PySide6/QtCore.pyd", "runtime/Lib/site-packages/PySide6/QtGui.pyd",
                "runtime/Lib/site-packages/PySide6/QtWidgets.pyd", "runtime/Lib/site-packages/PySide6/Qt6Core.dll",
                "runtime/Lib/site-packages/PySide6/Qt6Gui.dll", "runtime/Lib/site-packages/PySide6/Qt6Widgets.dll",
                "runtime/Lib/site-packages/PySide6/QtSvg.pyd", "runtime/Lib/site-packages/PySide6/Qt6Svg.dll",
                "runtime/Lib/site-packages/PySide6/plugins/platforms/qwindows.dll",
                "runtime/Lib/site-packages/openpyxl/__init__.py", "app/seoyoung_pos/app.py"]
    pe_checks = {}
    for relative in required:
        path = destination / relative
        if not path.is_file():
            raise RuntimeError(f"Required portable file missing: {relative}")
        if path.suffix.lower() in {".exe", ".dll", ".pyd"}:
            pe = pefile.PE(str(path), fast_load=True)
            if pe.FILE_HEADER.Machine != 0x8664:
                raise RuntimeError(f"Not a Windows x64 PE: {relative}")
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
            imports = [item.dll.decode("ascii") for item in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])]
            pe_checks[relative] = {"machine": "AMD64", "imports": imports}
            pe.close()
    # The launcher is also a valid Python zipapp containing the late entry point.
    with zipfile.ZipFile(destination / "SeoyoungPOS.exe") as archive:
        if archive.read("__main__.py").decode("utf-8") != ENTRYPOINT:
            raise RuntimeError("Executable entry point ZIP mismatch")
    # Traverse direct import dependencies from actual application runtime roots.
    # Windows API-set DLLs are supplied by Windows 10/11, not redistributed.
    windows_dlls = {
        "advapi32.dll", "authz.dll", "bcrypt.dll", "comdlg32.dll", "d3d9.dll", "d3d11.dll", "d3d12.dll",
        "dwmapi.dll", "dwrite.dll", "dxgi.dll", "gdi32.dll", "imm32.dll", "kernel32.dll", "mpr.dll",
        "netapi32.dll", "ole32.dll", "oleaut32.dll", "setupapi.dll", "shell32.dll", "shlwapi.dll",
        "uiautomationcore.dll", "user32.dll", "userenv.dll", "uxtheme.dll", "version.dll", "winmm.dll",
        "ws2_32.dll", "wtsapi32.dll",
    }
    dll_index = {path.name.lower(): path for path in destination.rglob("*")
                 if path.is_file() and path.suffix.lower() in {".dll", ".pyd", ".exe"}}
    pending = [destination / relative for relative in required if Path(relative).suffix.lower() in {".exe", ".dll", ".pyd"}]
    examined = set()
    external = set()
    while pending:
        path = pending.pop()
        if path in examined:
            continue
        examined.add(path)
        pe = pefile.PE(str(path), fast_load=True)
        if pe.FILE_HEADER.Machine != 0x8664:
            raise RuntimeError(f"Dependency is not Windows AMD64: {path.relative_to(destination)}")
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            name = entry.dll.decode("ascii").lower()
            if name in dll_index:
                pending.append(dll_index[name])
            elif name.startswith(("api-ms-win-", "ext-ms-win-")) or name in windows_dlls:
                external.add(name)
            else:
                raise RuntimeError(f"Application PE dependency not bundled or recognized as Windows system DLL: {name}")
        pe.close()
    return {"required_layout_files": len(required), "pe_x64_checks": pe_checks,
            "launcher_zip_entry_verified": True, "bundled_dependency_closure_count": len(examined),
            "external_windows_system_dlls": sorted(external), "windows_runtime_executed": False}


def write_archive(destination: Path, output: Path) -> Path:
    archive_path = output / "SeoyoungPOS-Windows-x64-portable.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(destination.rglob("*")):
            relative = path.relative_to(destination)
            if path.is_file() and relative.parts[0] not in {"data", "demo-data"} and "__pycache__" not in relative.parts:
                archive.write(path, Path("SeoyoungPOS") / relative)
    with zipfile.ZipFile(archive_path) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"Final archive corruption: {bad}")
    sha256 = digest(archive_path)
    archive_path.with_suffix(".zip.sha256").write_text(f"{sha256}  {archive_path.name}\n", encoding="ascii")
    print(f"Windows portable ZIP assembled (Windows execution unverified): {archive_path}", flush=True)
    print(f"SHA256: {sha256}", flush=True)
    return archive_path


def build(cache: Path, output: Path, *, refresh_source: bool = False, offline_cache: bool = False) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "SeoyoungPOS"
    runtime, wheels, upstream_manifest = upstream_artifacts(cache, offline_cache=offline_cache)
    distlib_wheel = next(path for path in wheels if path.name.startswith("distlib-"))
    pefile_wheel = next(path for path in wheels if path.name.startswith("pefile-"))
    if refresh_source:
        if not (destination / "PORTABLE-BUNDLE.json").is_file():
            raise RuntimeError("--refresh-source requires an existing generated bundle")
    else:
        if destination.exists():
            raise RuntimeError(f"Destination exists; use --refresh-source or a new output directory: {destination}")
        destination.mkdir()
        unpack_archive(runtime, destination / "runtime", prefix="tools/")
        for wheel in wheels:
            if wheel in {distlib_wheel, pefile_wheel}:
                continue
            unpack_archive(wheel, destination / "runtime" / "Lib" / "site-packages")
        (destination / "runtime" / "python312._pth").write_text(
            ".\nDLLs\nLib\nLib/site-packages\n../app\nimport site\n", encoding="ascii"
        )
        (destination / "시작 안내.txt").write_text(
            "서영 POS Windows x64 포터블\n\n"
            "1. ZIP 파일 전체를 쓰기 가능한 폴더에 압축 해제합니다.\n"
            "2. SeoyoungPOS.exe를 실행합니다. Python 설치나 인터넷은 필요하지 않습니다.\n"
            "3. 최초 실행에서 관리자 계정을 만듭니다.\n"
            "4. 실제 자료는 프로그램 폴더의 data 폴더에 보존합니다. 전체 폴더를 함께 보관하세요.\n"
            "5. 실행 오류는 startup-error.log 또는 diagnose.bat로 확인할 수 있습니다.\n\n"
            "Windows 10/11 x64용 바이너리를 Linux에서 조립한 패키지입니다.\n"
            "이 환경에서는 Windows 실행 검증을 수행하지 못했습니다. 실제 거래 전 Windows에서\n"
            "로그인·거래 등록·재실행·엑셀 내보내기·백업 및 복구를 확인하세요.\n"
            "배포 EXE는 애플리케이션 코드 서명이 없어 SmartScreen 안내가 표시될 수 있습니다.\n",
            encoding="utf-8-sig"
        )
    create_launcher(destination, distlib_wheel)
    license_sources = copy_licenses(destination, cache, offline_cache=offline_cache)
    (destination / "diagnose.bat").write_text(
        '@echo off\r\ncd /d "%~dp0"\r\n"runtime\\python.exe" "SeoyoungPOS.exe" %*\r\nset "pos_exit=%errorlevel%"\r\npause\r\nexit /b %pos_exit%\r\n', encoding="ascii"
    )
    source_hashes = copy_source(destination)
    validation = validate_layout(destination, pefile_wheel)
    report = {"package": "Seoyoung POS", "target": "Windows x64", "python": "3.12.10",
              "assembly_host": sys.platform, "distribution_type": "relocatable distlib launcher + CPython runtime",
              "build_mode": "verified_offline_cache" if offline_cache else "online_metadata_and_verified_cache",
              "offline_cache": offline_cache, "wheel_metadata_fetched": not offline_cache,
              "upstream_integrity": upstream_manifest, "license_sources": license_sources,
              "source_sha256": source_hashes, "validation": validation}
    (destination / "PORTABLE-BUNDLE.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "build-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return write_archive(destination, output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("/workspace/downloads-pos"))
    parser.add_argument("--output", type=Path, default=Path("/workspace/artifacts/windows-portable"))
    parser.add_argument("--refresh-source", action="store_true", help="Refresh app source in this script's existing bundle and rezip")
    parser.add_argument("--offline-cache", action="store_true",
                        help="Require all pinned artifacts/licenses in --cache; verify hashes without any network requests")
    args = parser.parse_args()
    build(args.cache.resolve(), args.output.resolve(), refresh_source=args.refresh_source, offline_cache=args.offline_cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
