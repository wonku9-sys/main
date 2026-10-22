"""Assemble a relocatable Windows runtime bundle; not a native Windows test.

Inputs are a previously integrity-verified CPython 3.12 x64 runtime and official
Windows wheels. Does not publish source or use a third-party build service.
"""
import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import struct
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
ENTRY = '''from pathlib import Path
import ctypes
import sys
import tempfile
import traceback
try:
    from pos2.app import main
    arguments = sys.argv[1:]
    # A working test bundle must not silently open the installed application's
    # existing LOCALAPPDATA database. Its own new folder is the safe default.
    if '--data-dir' not in arguments and not any(a.startswith('--data-dir=') for a in arguments):
        arguments = ['--data-dir', str(Path(sys.executable).resolve().parent.parent / 'trial-data-v2'), *arguments]
    raise SystemExit(main(arguments) or 0)
except Exception:
    detail = traceback.format_exc()
    log = Path(tempfile.gettempdir()) / 'SY-POS-startup-error.log'
    try:
        log.write_text(detail, encoding='utf-8')
    except OSError:
        pass
    ctypes.windll.user32.MessageBoxW(None,
        'SY POS를 시작하지 못했습니다.\\n오류 기록: ' + str(log) + '\\n\\n' + detail[-1500:],
        'SY POS 실행 안내', 0x10)
    raise SystemExit(1)
'''


def digest(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()


def verified_wheel(path):
    with ZipFile(path) as archive:
        if archive.testzip():
            raise ValueError('Wheel CRC failed: '+path.name)
        records = [n for n in archive.namelist() if n.endswith('.dist-info/RECORD')]
        if len(records) != 1:
            raise ValueError('Missing wheel RECORD')
        for name, check, size in csv.reader(io.StringIO(archive.read(records[0]).decode())):
            if not check:
                continue
            algorithm, expected = check.split('=', 1)
            data = archive.read(name)
            actual = base64.urlsafe_b64encode(hashlib.new(algorithm, data).digest()).decode().rstrip('=')
            if actual != expected or len(data) != int(size):
                raise ValueError('Wheel integrity failed: '+name)


def assemble(runtime, wheels, output, build_label='purchase-payment', source_zip=None):
    from package_source import source_files
    from pos2 import __version__
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}',build_label):
        raise ValueError('Use a short ASCII build label without path separators.')
    if output.exists():
        raise ValueError('Choose a new output directory; existing files are preserved.')
    bundle = output/'SY-POS'
    bundle.mkdir(parents=True)
    # Only the interpreter/libraries are reused, never the older application.
    shutil.copytree(runtime, bundle/'runtime', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'pip', 'pip-*.dist-info'))
    sites = bundle/'runtime'/'Lib'/'site-packages'
    wheel_rows = []
    for wheel in sorted(wheels.glob('*.whl')):
        verified_wheel(wheel)
        wheel_rows.append(dict(name=wheel.name, sha256=digest(wheel)))
        if wheel.name.startswith('distlib-'):
            with ZipFile(wheel) as archive:
                launcher = archive.read('distlib/w64.exe')
                notice = next(n for n in archive.namelist() if n.endswith('/LICENSE.txt'))
                (bundle/'licenses').mkdir(exist_ok=True)
                (bundle/'licenses'/'distlib-LICENSE.txt').write_bytes(archive.read(notice))
            continue
        with ZipFile(wheel) as archive:
            for name in archive.namelist():
                if name.endswith('/'):
                    continue
                target = (sites/name).resolve()
                if not target.is_relative_to(sites.resolve()) or '.data' in Path(name).parts:
                    raise ValueError('Unsupported wheel layout: '+name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
    if '<launcher_dir>\\'.encode('utf-16-le') not in launcher:
        raise ValueError('Launcher must support relocatable runtime paths.')
    payload = io.BytesIO()
    with ZipFile(payload, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('__main__.py', ENTRY)
    (bundle/'SY-POS.exe').write_bytes(launcher+b'#!"<launcher_dir>\\runtime\\pythonw.exe"\n'+payload.getvalue())
    excluded = {'arcade.py','arcade_ui.py','rom_library.py','rom_library_ui.py'}
    for source in source_files():
        if not source.is_relative_to(ROOT):
            continue
        relative = source.relative_to(ROOT)
        if relative.parts[0] == 'pos2' and source.name not in excluded:
            target = bundle/'app'/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    for source in (ROOT/'third-party-licenses').glob('*.txt'):
        shutil.copy2(source, bundle/'licenses'/source.name)
    for name in ('README.md', 'OPTIMIZATION_REVIEW.md', 'PURCHASE_PAYMENT_REVIEW.md','PRIVATE_TRIAL.md','PDF_COMPLETION.md'):
        shutil.copy2(ROOT/name, bundle/name)
    (bundle/'runtime'/'python312._pth').write_text('.\nDLLs\nLib\nLib/site-packages\n../app\nimport site\n', encoding='ascii')
    (bundle/'실행 안내.txt').write_text(
        'Windows 10/11 x64용 SY POS\n\n'
        'ZIP 전체를 새 폴더에 압축 해제한 뒤 SY-POS.exe를 실행하세요.\n'
        'Python을 따로 설치하지 않아도 됩니다. EXE만 분리하지 마세요.\n'
        '기존 프로그램 폴더를 덮어쓰거나 업무자료를 삭제하지 마세요.\n'
        '이 패키지는 Linux에서 공식 Windows 런타임으로 구성했습니다.\n'
        '완성본이 아닌 시험용 작업본입니다. 새 trial-data-v2 폴더로 시작합니다.\n'
        '기존 업무자료를 자동으로 열지 않습니다. 실제 매장 DB를 덮어쓰지 마세요.\n'
        '실제 Windows 기동/프린터/장비 테스트는 미검증입니다.\n'
        '인증서로 서명되지 않아 Windows 게시자 경고가 표시될 수 있습니다.\n'
        '보안 설정을 끄지 마세요. 기존 자료는 사용 전 별도 백업하세요.\n', encoding='utf-8-sig')
    # Verify all PE modules are x64, including the launcher and crypto extension.
    pe_count = 0
    for path in bundle.rglob('*'):
        if path.suffix.lower() not in {'.exe','.dll','.pyd'}:
            continue
        with path.open('rb') as stream:
            header = stream.read(64)
            if header[:2] != b'MZ':
                raise ValueError('Invalid Windows binary: '+str(path))
            stream.seek(struct.unpack_from('<I', header, 60)[0])
            signature, machine = struct.unpack('<4sH', stream.read(6))
            if signature != b'PE\0\0' or machine != 0x8664:
                raise ValueError('Non-x64 Windows binary: '+str(path))
        pe_count += 1
    files = {}
    for path in bundle.rglob('*'):
        if path.is_file():
            relative = path.relative_to(bundle)
            qt_icu = relative.as_posix() == 'runtime/Lib/site-packages/PySide6/resources/icudtl.dat'
            if path.suffix.lower() in {'.db','.sqlite','.sqlite3','.key','.pem','.dat','.idx','.rom','.nes'} and not qt_icu:
                raise ValueError('Private/business data must not be packaged: '+str(relative))
            files[relative.as_posix()] = digest(path)
    manifest = dict(version=__version__, variant='purchase-payment', type='relocatable-Windows-x64-runtime',
                    build_label=build_label,native_windows_tested=False,test_data_directory='trial-data-v2',
                    pe_x64_count=pe_count, wheels=wheel_rows, files=files)
    if source_zip is not None:
        manifest['matching_source']=dict(name=Path(source_zip).name,sha256=digest(Path(source_zip)))
    (bundle/'BUNDLE-MANIFEST.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    archive_path = output/f'SY-POS-v{__version__}-{build_label}-Windows-x64-TEST.zip'
    with ZipFile(archive_path, 'w', ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(output))
    with ZipFile(archive_path) as archive:
        if archive.testzip():
            raise ValueError('Bundle ZIP CRC failed')
    archive_path.with_suffix('.zip.sha256').write_text(digest(archive_path)+'  '+archive_path.name+'\n', encoding='utf-8')
    print(archive_path, flush=True)
    print('SHA256', digest(archive_path), 'x64 PE files', pe_count, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--wheels', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--build-label',default='purchase-payment')
    parser.add_argument('--source-zip',type=Path)
    args = parser.parse_args()
    assemble(args.runtime, args.wheels, args.output,args.build_label,args.source_zip)
