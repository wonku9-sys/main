"""Build only the clean standalone POS; run on Windows for a Windows release."""

import argparse
from hashlib import sha256
from importlib import metadata
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import sysconfig
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

from pos2 import __version__

ROOT = Path(__file__).resolve().parent
APP = "SY-POS"
DISTRIBUTIONS = ("PySide6", "PySide6-Essentials", "PySide6-Addons", "shiboken6", "openpyxl", "xlrd", "et-xmlfile", "python-barcode", "pyinstaller","cryptography","cffi","pycparser","korean-lunar-calendar")


def licenses(destination):
    """Distribute original third-party notices, not application source from elsewhere."""
    lines = ["# Third-party components", "", "Original license and notice files accompany the runtime in this directory.", ""]
    destination.mkdir()
    qt_notices = ROOT / "third-party-licenses"
    for source in qt_notices.glob("*.txt"):
        shutil.copy2(source, destination / source.name)
    if not (destination / "Qt-LGPL-3.0-only.txt").exists():
        raise RuntimeError("The original Qt LGPL notice must accompany the standalone source.")
    python_notice = next((path for path in (Path(sys.base_prefix) / "LICENSE.txt", Path(sysconfig.get_path("stdlib")) / "LICENSE.txt") if path.is_file()), None)
    if python_notice is None:
        raise RuntimeError("The Python interpreter's original LICENSE.txt must be available before distribution.")
    shutil.copy2(python_notice, destination / "Python-LICENSE.txt")
    shutil.copy2(ROOT / "pos2" / "assets" / "OFL.txt", destination / "NotoSansKR-OFL.txt")
    shutil.copy2(ROOT / "pos2" / "assets" / "FONT_SOURCE.md", destination / "NotoSansKR-SOURCE.md")
    for name in DISTRIBUTIONS:
        distribution = metadata.distribution(name)
        copied = 0
        for entry in distribution.files or ():
            parts = entry.parts
            lowered = [part.lower() for part in parts]
            if not any("license" in part or "licence" in part or part.startswith("copying") or part.startswith("notice") for part in lowered):
                continue
            source = Path(distribution.locate_file(entry))
            if not source.is_file() or source.suffix.lower() not in {"", ".txt", ".md", ".rst", ".html", ".json", ".python",".apache",".bsd",".openssl"}:
                continue
            safe = [part for part in parts if part not in {"..", ".", "/"}]
            target = destination / name / Path(*safe)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied += 1
        lines.append(f"- {distribution.metadata['Name']} {distribution.version}: {copied} original notice files; {distribution.metadata.get('License-Expression') or distribution.metadata.get('License') or 'see notices'}")
        if not copied and name not in {"PySide6", "PySide6-Essentials", "PySide6-Addons", "shiboken6"}:
            raise RuntimeError(f"No original license notice found for {name}; do not distribute an incomplete package.")
    lines.extend(["", "Qt for Python (PySide6 / Shiboken6) uses the accompanying Qt-LGPL-3.0-only.txt and Qt-GPL-3.0-only.txt notices.",
                  "Qt for Python source and license options: https://www.qt.io/qt-for-python / https://code.qt.io/pyside/pyside-setup.git/",
                  "The application uses dynamically linked Qt libraries in _internal; no restriction on replacing those libraries is imposed."])
    (destination / "COMPONENTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_entry(path):
    relative = path.as_posix().lower()
    if path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".env", ".key", ".pem", ".nes", ".smc", ".sfc", ".rom", ".gba", ".gb", ".gbc", ".mp3"} or relative.endswith(("-wal", "-shm")):
        raise RuntimeError(f"Business data or private file must never be packaged: {path}")
    if "seoyoung_pos" in relative or {"data-v2","approved-games","unsaved-work","mini-arcade","lucky-audio"}&set(path.parts) or path.name.lower() in {'bublbobl.zip','bublbob2.zip','freesound_community-winning-82808.mp3','u_xmiiqyhi46-gamestart-272829.mp3'}:
        raise RuntimeError(f"Legacy application or business data path detected: {path}")


def build(output, native=False):
    if sys.platform != "win32" and not native:
        raise RuntimeError("Windows EXE must be built on Windows. Use --native only for a clearly labelled local-platform validation build.")
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("This release target is x64 only.")
    label = "Windows" if sys.platform == "win32" else "Linux" if sys.platform.startswith("linux") else platform.system()
    output = output.resolve()
    bundle = output / APP
    archive = output / f"{APP}-v{__version__}-{label}-x64-portable.zip"
    if bundle.exists() or archive.exists() or archive.with_suffix(archive.suffix + ".sha256").exists():
        raise RuntimeError("Output already exists. Preserve it and choose a fresh --output directory.")
    if not (ROOT / "README.md").is_file():
        raise RuntimeError("The independent application's README.md is required before packaging.")
    output.mkdir(parents=True, exist_ok=True)
    assets = ROOT / "pos2" / "assets"
    font = assets / "NotoSansKR-Regular.ttf"
    if not font.is_file() or sha256(font.read_bytes()).hexdigest() != "194018e6b2b293a7964f037b25c0249ce1418bc9ab3c971060a03aa57861e252":
        raise RuntimeError("The verified offline Korean font asset is missing or changed.")
    with tempfile.TemporaryDirectory(prefix="seoyoung-standalone-build-") as scratch:
        temporary = Path(scratch)
        # Windows ICO supports a PNG payload (Vista+). Generate from the same
        # original logo using Qt; no extra imaging runtime is needed.
        from PySide6.QtCore import QBuffer, QIODevice, Qt
        from PySide6.QtGui import QImage
        image=QImage(str(assets / "sy-monogram.png"))
        if image.isNull():raise RuntimeError("The SY POS logo image is missing.")
        canvas=QImage(256,256,QImage.Format.Format_ARGB32);canvas.fill(0)
        from PySide6.QtGui import QPainter
        painter=QPainter(canvas)
        scaled=image.scaled(256,256,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        painter.drawImage((256-scaled.width())//2,(256-scaled.height())//2,scaled);painter.end()
        buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);canvas.save(buffer,"PNG")
        payload=bytes(buffer.data());icon=temporary / "sy-pos.ico"
        icon.write_bytes(struct.pack("<HHH",0,1,1)+struct.pack("<BBBBHHII",0,0,0,0,1,32,len(payload),22)+payload)
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed", "--name", APP,
                   "--paths", str(ROOT), "--distpath", str(output), "--workpath", str(temporary / "work"), "--specpath", str(temporary),
                   "--icon",str(icon),"--add-data", f"{assets}{os.pathsep}pos2/assets", "--hidden-import", "PySide6.QtPrintSupport", "--hidden-import", "PySide6.QtSvg", "--hidden-import","PySide6.QtMultimedia", "--collect-all", "barcode", "--exclude-module", "seoyoung_pos", str(ROOT / "launch.py")]
        build_environment = dict(os.environ)
        build_environment["PYINSTALLER_CONFIG_DIR"] = str(temporary / "cache")
        subprocess.run(command, cwd=ROOT, env=build_environment, check=True)
    executable = bundle / (APP + ".exe" if sys.platform == "win32" else APP)
    if not executable.is_file():
        raise RuntimeError("The frozen executable was not created.")
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "windows" if sys.platform == "win32" else "offscreen"
    screenshot = output / f"{APP}-{label}-smoke.png"
    subprocess.run([str(executable), "--smoke-test", "--screenshot", str(screenshot)], cwd=bundle, env=environment, check=True, timeout=180)
    if not screenshot.is_file() or screenshot.stat().st_size < 1000:
        raise RuntimeError("The real frozen executable did not produce its desktop screenshot.")
    for suffix in ("-home", "-purchase", "-return", "-product-search", "-categories", "-backup", "-payments", "-login", "-permissions","-suppliers","-supplier-groups","-product-units","-reports","-quotation","-diary","-household","-health","-schedule","-alerts","-mail-settings","-accounts","-fixed-costs","-vehicles","-attachments","-personal-schedule","-inspiration","-pc-connection","-health-report","-vehicle-report","-vehicle-payments","-classification","-opening-stock","-stock-waste","-inventory-assets","-member-details","-email-recovery","-independent-windows","-lucky-numbers","-financial-overview","-savings-goals","-category-budgets","-annual-household","-custom-household-reports","-worklog-dashboard","-worklog-productivity","-sales-comparison"):
        capture = screenshot.with_name(screenshot.stem + suffix + screenshot.suffix)
        if not capture.is_file() or capture.stat().st_size < 1000:
            raise RuntimeError(f"The frozen executable did not validate its new workflow screen: {suffix}")
    for suffix in ('-worklog-independent','-diary-independent','-lucky-mixing','-new-product-categories','-product-category-search','-product-search-continuous','-shortcut-guide','-inventory-categories','-inventory-suppliers','-inventory-monthly','-resized-fixed-query'):
        capture=screenshot.with_name(screenshot.stem+suffix+screenshot.suffix)
        if not capture.is_file() or capture.stat().st_size<1000:
            raise RuntimeError(f"The frozen executable did not validate visible single-window content: {suffix}")
    if label == "Windows":
        for suffix in ('-store-profile','-orders','-order-editor','-paper-a4','-commercial-preview','-arcade-lobby','-game-blocks','-game-gomoku','-game-shooter','-game-jumper','-game-bubbles','-game-raccoon','-approved-game-library','-catalog-tree-tax','-product-tax-details','-product-change-log','-product-member-prices','-catalog-excel-preview','-crash-recovery'):
            capture=screenshot.with_name(screenshot.stem+suffix+screenshot.suffix)
            if not capture.is_file() or capture.stat().st_size<1000:raise RuntimeError(f'The frozen executable did not validate its new document/game/recovery screen: {suffix}')
        (bundle / "체험 실행.bat").write_bytes(b'@echo off\r\ncd /d "%~dp0"\r\n"SY-POS.exe" --demo\r\n')
    documents = bundle / "안내문서"
    documents.mkdir()
    for source in sorted(ROOT.glob("*.md")):
        if source.name != "CONTRACT.md":
            shutil.copy2(source, documents / source.name)
    (bundle / "먼저_읽어주세요.txt").write_text(
        f"SY POS 독립판 {__version__}\n\n"
        + ("Windows 10/11 x64용 무설치 프로그램입니다.\n" if label == "Windows" else f"주의: 이 파일은 {label} 검증용이며 Windows 프로그램이 아닙니다.\n")
        + f"ZIP 전체를 쓰기 가능한 폴더에 압축 해제하고 {executable.name}을 실행하세요.\n"
        "Python 설치·서버·인터넷·카드 연동이 필요하지 않습니다.\n"
        "날씨·인터넷 시각 표시는 선택 기능입니다. 첫화면에서 지역을 직접 정하고 켜세요. 자동 위치 조회는 하지 않습니다.\n"
        "일정 알림은 실행 중 표시하며 놓친 알림은 다음 실행 때 확인합니다. 양력·음력 연간 반복 및 경과 일수를 지원합니다.\n"
        "일기장·가계부는 별도 팝업입니다. 이메일 복구는 암호를 잊기 전에 등록해야 하며 개인 자료는 최초 등록 이메일의 복구키도 필요합니다.\n"
        "금액은 소수점 두 자리로 보존합니다. 2.2 이하 장부는 처음 열 때 보호 백업 후 형식을 업그레이드합니다. 업그레이드 후에는 이전 EXE로 열지 마세요.\n"
        "새 장부의 초기 아이디 admin / 초기 비밀번호 1234 (로그인 창 하단에도 표시).\n"
        "공개된 초기 비밀번호입니다. 최초 로그인 시 8~128자의 새 로그인 암호를 반드시 설정해야 합니다.\n"
        "자료는 실행 파일 옆 data-v2 폴더의 seoyoung-standalone-v2.db에 보존됩니다.\n"
        "단독 사용이 기본입니다. PC 연결 설정에서 기준 PC를 선택하면 같은 내부망의 연결 PC와 업무 장부만 공유합니다. 기준 PC가 켜져 있어야 합니다.\n"
        "연결 PC 개인 자료는 data-v2/personal 아래에 별도로 저장됩니다. 일기장·가계부·건강·첨부파일은 다른 PC에 보내지 않습니다.\n"
        "가계부의 통장 잔액은 직접 기록한 자료이며 은행과 자동 연동하지 않습니다. 고정비는 잠금 해제 후 미반영분을 기록할 뿐 실제 송금하지 않습니다.\n"
        "차량 유지비는 가계부 지출 1건으로 연결됩니다. 첨부한 사진·문서도 장부 백업에 포함됩니다.\n"
        "기념일 문자는 복사 가능한 초안만 제공하며 실제 SMS 발송·요금은 발생하지 않습니다.\n"
        "프로그램 폴더를 옮길 때 data-v2 폴더를 함께 옮기고, 정기적으로 설정의 백업을 이용하세요.\n"
        "설정에서 백업 목록을 선택해 복원할 수 있습니다. 적용하면 현재 자료가 교체되고 프로그램이 종료됩니다.\n"
        "백업 폴더는 자동 생성합니다. 7일마다 오래된 관리 백업을 삭제하되 최신 15개를 남기고 알립니다.\n"
        "기존 서영 POS 프로그램 및 DB를 가져오거나 덮어쓰지 않는 완전히 별도의 독립판입니다.\n"
        "USB 스캐너는 HID 키보드(Enter 접미사) 모드, 프린터는 Windows 드라이버를 사용합니다.\n"
        "세부 실행법과 제외 기능은 안내문서/README.md를 확인하세요.\n", encoding="utf-8-sig")
    licenses(bundle / "third-party-licenses")
    files = sorted(path for path in bundle.rglob("*") if path.is_file())
    for path in files:
        check_entry(path.relative_to(bundle))
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=9) as stream:
        for path in files:
            stream.write(path, path.relative_to(output))
    with ZipFile(archive) as stream:
        if stream.testzip() is not None:
            raise RuntimeError("Portable ZIP failed its CRC integrity check.")
        for entry in stream.namelist():
            check_entry(Path(entry))
    digest = sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(archive.suffix + ".sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"Built and smoke-tested {label} portable: {archive} ({archive.stat().st_size:,} bytes)\nSHA256 {digest}", flush=True)
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--native", action="store_true", help="Allow a clearly platform-labelled non-Windows test bundle.")
    options = parser.parse_args()
    build(options.output, options.native)
