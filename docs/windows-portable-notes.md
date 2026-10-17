# Windows 포터블 패키지

`scripts/windows_portable.py`는 Windows용 CPython과 Qt 바이너리를 모아 Windows x64 포터블 프로그램을 조립합니다. Linux에서 수행한 조립 결과와 Windows 실행 검증은 별개입니다. 이 환경에서는 Windows 실행을 검증하지 않았습니다.

```bash
python scripts/windows_portable.py \
  --cache /workspace/downloads-pos \
  --output /workspace/artifacts/windows-portable
```

기존 조립 결과에 최신 애플리케이션 소스를 반영하려면 동일한 명령에 `--refresh-source`를 추가합니다. 실제 운영 자료를 배포 압축 파일에 넣지 않습니다. 다른 PC에 프로그램을 업데이트할 때 기존 `data` 폴더를 보존해야 합니다.

압축 파일 전체를 쓰기 가능한 폴더에 해제한 뒤 `SeoyoungPOS.exe`를 실행합니다. Python 설치, 서버, 실행 시 인터넷 연결은 필요하지 않습니다. 기본 거래 자료는 EXE 옆의 `data` 폴더에 보존합니다. 이 위치에 쓸 수 없으면 프로그램의 사용자별 자료 폴더로 전환합니다. `--data-dir`를 직접 지정한 경우에는 지정한 경로를 따릅니다.

```text
SeoyoungPOS/
  SeoyoungPOS.exe       Windows x64 GUI 실행 파일
  runtime/             CPython 3.12.10, Qt/PySide6, 엑셀 라이브러리
  app/seoyoung_pos/     실행되는 프로그램 코드
  licenses/            실행 파일 런처의 저작권 고지
  PORTABLE-BUNDLE.json 빌드 입력과 검증 결과
  diagnose.bat         오류 확인용 콘솔 실행
  data/                최초 실제 실행 후 생성되는 거래 자료
```

EXE는 distlib의 공식 사전 빌드 GUI 런처에 Python ZIP 진입점을 추가한 파일입니다. 런처는 지원되는 `<launcher_dir>` 경로를 통해 같은 폴더의 `runtime/pythonw.exe`를 실행합니다. 별도 Python 설치나 PATH에 의존하지 않으며, Python의 `._pth` 설정으로 시스템 패키지와 환경 변수로부터 분리합니다. 프로그램 코드와 데이터는 실행 파일과 함께 이동할 수 있습니다. 애플리케이션 EXE 코드 서명은 포함하지 않으므로 Windows SmartScreen 안내가 표시될 수 있습니다.

의존성은 Python Software Foundation이 NuGet에 게시한 Python 3.12.10의 카탈로그 SHA512와 PyPI가 게시한 Windows wheel SHA256으로 검증합니다. TLS 인증서 검증과 모든 원본 해시를 유지합니다. 재빌드 스크립트에 해시를 고정했으며 패키지의 라이선스·메타데이터를 보존합니다. `runtime/LICENSE.txt`는 CPython 라이선스이고, Qt/PySide의 라이선스 고지는 해당 패키지의 `.dist-info`와 배포 파일에 있습니다.

Linux에서 검증하는 항목은 원본 다운로드 무결성, ZIP 무결성, 필수 파일 존재, 실행 파일·Python·SQLite·Qt 핵심 라이브러리의 PE AMD64 형식, 실행 파일 내 ZIP 진입점입니다. `build-report.json`의 `windows_runtime_executed` 값은 이 검증이 Windows 실행을 포함하지 않음을 명시합니다. Windows에서의 네이티브 PyInstaller 빌드·실행 검증은 `build_windows.bat`와 GitHub Actions 워크플로가 담당합니다.

실제 영업 전에 Windows 10/11 x64에서 최초 관리자 등록, 사용자 권한, 공급사와 상품 등록, 매입·매출, 금액·잔액·재고, 종료 후 자료 유지, 엑셀 내보내기 및 백업/복구를 확인해야 합니다. `SeoyoungPOS.exe --demo --smoke-test`로 준비된 스모크 검증도 실행할 수 있습니다. 이 패키지를 Windows에서 실행했다는 결과는 아직 없습니다.
