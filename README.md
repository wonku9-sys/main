# 서영 POS

육류 매장의 매입·매출, 거래처 잔액, 상품과 재고를 관리하는 한글 데스크톱 프로그램입니다. PySide6(Qt)와 SQLite를 사용하며, 설치된 프로그램은 서버와 인터넷 연결 없이 동작합니다.

참고 사진의 **좌측 업무 메뉴 → 상단 바로가기 → 검색 조건 → 거래 목록 → 합계** 흐름을 살리고, 현대적인 색상·간격·정보 카드로 다시 구성했습니다. 상품에서 매입 이력을 확인하고, 공급사를 선택한 뒤 매입전표를 입력하는 업무 흐름을 지원합니다. 사진 속 실제 거래처·상품·거래자료는 가져오지 않습니다.

## Windows에서 실행

지원 대상은 **Windows 10/11 64비트**입니다. Qt 6.8 기준 Windows 10은 1809 이상이 필요합니다.

Windows에서 빌드된 `SeoyoungPOS-Windows-x64-portable.zip`이 있는 경우:

1. ZIP 전체를 문서 폴더 등 쓰기 가능한 로컬 폴더에 압축 해제합니다.
2. `SeoyoungPOS` 폴더 안의 `SeoyoungPOS.exe`를 실행합니다.
3. 최초 실행 화면에서 관리자 아이디·이름·비밀번호를 직접 등록합니다. 공용 초기 관리자 비밀번호는 없습니다.
4. 공급사/고객과 상품을 등록한 뒤 매입·매출 전표를 입력합니다.

폴더 전체가 프로그램입니다. 제공된 런타임 포함 번들은 `runtime`·`app` 폴더를, Windows PyInstaller 빌드는 `_internal` 폴더를 함께 유지해야 합니다. EXE만 따로 옮기면 실행되지 않습니다. 두 방식 모두 Python 설치는 필요 없습니다. 네트워크 공유 드라이브와 동기화 중인 폴더에 거래 DB를 두지 마세요. 현재 프로그램은 한 대의 PC에서 사용하는 단독 실행 방식입니다.

이 작업에 포함된 런타임 번들 제작 방식은 공식 Windows Python 3.12 런타임과 Windows용 의존성을 묶어 `SeoyoungPOS.exe`로 실행합니다. 런타임과 다운로드 파일의 무결성은 검증하지만, Linux에서 제작한 번들을 Windows에서 직접 실행한 검증은 별개입니다. 구성·검증 범위와 Windows 확인 방법은 [Windows 포터블 번들 안내](docs/windows-portable-notes.md)를 참고하세요. Windows PC에서 직접 만드는 PyInstaller 빌드는 아래 제작 절차를 사용합니다.

이 저장소의 Windows 빌드는 코드 서명이 적용되지 않았습니다. 배포 출처와 제공된 SHA256을 확인한 뒤 실행하세요. Windows SmartScreen 경고 여부는 PC 정책과 배포 이력에 따라 달라집니다.

## 소스에서 실행

Windows에서는 Python 3.12 x64를 설치한 뒤 `run_windows.bat`를 실행하면 됩니다. 처음 한 번은 가상환경과 의존성을 설치하므로 인터넷이 필요합니다. 이후에는 설치된 환경으로 오프라인 실행합니다. 소스를 ZIP으로 받은 경우 먼저 전체 압축을 해제하세요.

직접 실행하는 명령은 다음과 같습니다.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m seoyoung_pos
```

Linux 개발 환경에서는 다음 명령을 사용합니다. 일반 화면 실행에는 데스크톱 세션과 Qt 시스템 라이브러리가 필요합니다.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m seoyoung_pos
```

`uv`가 있는 클라우드 개발 환경에서는 저장소의 `uv.lock`으로 동일한 의존성을 재현할 수 있습니다. 기존 체크아웃을 사용하며 별도의 Git 작업 트리를 만들 필요는 없습니다.

```bash
uv sync --frozen --extra dev
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m seoyoung_pos --demo --smoke-test
```

샘플 자료로 화면을 살펴보려면 `--demo`를 붙입니다. 데모는 업무 데이터와 분리되며 화면에 데모 표시가 나타납니다.

```powershell
.venv\Scripts\python.exe -m seoyoung_pos --demo
```

데모 비밀번호는 `Demo-2026!`입니다. 데모 계정은 실제 업무용 관리자 계정과 관계가 없습니다. 업무용 계정의 비밀번호를 데모 비밀번호로 설정하지 마세요.

## 업무 흐름

| 화면 | 사용하는 작업 |
| --- | --- |
| 대시보드 | 매입·매출 현황과 미결제 잔액 확인, 주요 업무 바로가기 |
| 공급사·고객 | 코드, 명칭, 사업자번호, 담당자, 전화, 은행·계좌·예금주, 메모 관리 |
| 상품 | 코드·바코드, 상품명, 분류, 규격·단위, 원산지, 매입·판매 단가, 최소 재고 관리 |
| 매입전표 | 공급사 검색·선택 후 상품별 수량·단가를 입력하고 매입/지급액 저장 |
| 매출전표 | 고객을 선택하고 상품·수량·단가·수금액을 입력해 매출 저장 |
| 입출금·정산 | 거래처의 남은 매입대금 또는 매출대금에 추가 지급·수금 등록 |
| 재고 | 매입·매출과 연동된 현재고 확인, 사유를 남기는 재고 조정 |
| 조회·엑셀 | 기간·거래처·상품 검색, 검색 결과 합계, `.xlsx` 내보내기 |
| 사용자·설정 | 관리자/일반 사용자, 사용자별 권한, 비밀번호, 백업 관리 |

목록의 열 제목으로 정렬하고, 열 경계를 드래그해 너비를 조절할 수 있습니다. 검색 후 표시되는 합계는 현재 검색 결과를 기준으로 합니다. 금액과 미결제 잔액은 구분해 표시합니다.

대시보드의 기간 조건은 매입·매출·이익 집계에 적용됩니다. 미지급·미수금과 재고는 기간 말의 과거 스냅샷이 아닌 **현재 잔액·현재고**입니다.

수량은 소수점 셋째 자리까지, 단가는 상품 기본 단위당 정수 원 단위로 관리합니다. 예를 들어 상품 단위가 `kg`이면 수량 `1.250`은 1.25kg이며, 단가가 12,000원이면 금액은 15,000원입니다. 행별 수량×단가는 원 단위에서 반올림(ROUND_HALF_UP)하며, 행 금액의 합계가 전표 합계입니다. 100g 기준 단가를 쓰는 상품은 기본 단위와 단가를 그 기준에 맞게 등록해야 합니다. 서로 다른 단위 간의 자동 환산은 제공하지 않습니다.

전표 저장은 거래 금액·지급/수금·재고 변동을 함께 처리합니다. 재고평가는 이동평균원가를 사용하며, 매출 시점의 원가를 기록합니다. 저장된 전표를 취소할 때에는 확인 절차를 거칩니다. 지급/수금이 있거나 재고·원가를 안전하게 되돌릴 수 없는 전표의 취소는 제한됩니다. 전용 반품 전표, 영수증·프린터 출력, 카드 단말기, 전자세금계산서·세무 신고 연동은 현재 제공하지 않습니다.

원가는 전표의 **실제 등록 순서**로 계산합니다. 과거 날짜의 전표를 나중에 입력해도 과거 전체 원가를 재계산하지 않고 등록 시점의 이동평균을 적용합니다. 해당 매입 뒤 유효한 매출이나 재고 감소 조정이 있는 경우에는 재고 수량이 충분해도 매입 취소를 차단합니다. 관련 매출을 먼저 취소한 경우에는 다시 판단합니다. 과거 전표의 직접 수정, 기존 POS 데이터의 자동 이관, 법정 회계장부 기능은 제공하지 않습니다.

## 로그인과 권한

처음 만든 계정이 관리자가 됩니다. 관리자는 일반 사용자에게 필요한 업무 권한을 설정할 수 있습니다. 사용자 관리와 관리자 설정은 관리자만 사용할 수 있습니다. 화면 접근뿐 아니라 저장 처리에서도 권한을 확인합니다.

비밀번호는 개별 솔트와 안전한 비밀번호 해시로 저장합니다. 사용자 삭제에는 확인창이 표시되며 현재 로그인한 계정과 마지막 관리자 계정은 삭제할 수 없습니다. 거래 이력이 있는 사용자도 감사 추적을 위해 삭제를 제한하며, 필요한 경우 업무 권한을 해제할 수 있습니다. 업무 기록을 보존하기 위해 거래 이력이 있는 거래처·상품의 삭제도 제한됩니다.

## 데이터 위치와 백업

거래자료는 SQLite 파일에 저장되므로 프로그램을 종료해도 보존됩니다.

업무용 DB 파일명은 `seoyoung.db`, 데모 DB 파일명은 `seoyoung-demo.db`입니다.

- Windows 포터블 EXE: EXE 옆 `data` 폴더를 우선 사용합니다. 해당 위치에 쓸 수 없으면 `%LOCALAPPDATA%\SeoyoungPOS`를 사용합니다.
- 소스 실행: 운영체제의 사용자별 애플리케이션 데이터 폴더를 사용합니다.
- `--data-dir "D:\SeoyoungData"`: 데이터 폴더를 직접 지정할 수 있습니다. 테스트 폴더와 실제 업무 폴더를 혼용하지 마세요.
- 데모 모드: 별도의 데모 저장소를 사용합니다.

현재 데이터 위치는 프로그램 설정/상태 표시에서 확인하세요. 중요한 거래자료는 정기적으로 프로그램의 **백업** 기능으로 다른 디스크에 보관하세요. 백업은 SQLite 온라인 백업과 무결성 검사를 사용하며 기존 백업 파일을 덮어쓰지 않습니다. 실행 중인 SQLite 파일 하나를 탐색기로 복사하면 최신 거래가 누락될 수 있으므로 프로그램의 백업 기능을 사용하세요. 업데이트할 때에는 먼저 백업하고 기존 데이터 폴더를 유지하세요. 샘플 데이터로 실제 데이터 파일을 덮어쓰지 마세요. 자동 복원 화면은 제공하지 않으므로 복원이 필요하면 프로그램을 완전히 종료하고 기존 데이터 폴더를 별도로 보관한 후 검증된 백업으로 교체해야 합니다.

프로그램에 저장하는 거래처·계좌·거래 정보는 PC 사용자의 파일 접근 권한으로 보호됩니다. 로그인은 애플리케이션 권한을 구분하며 DB 파일 자체를 암호화하지는 않습니다. Windows 계정과 디스크 접근 권한을 함께 관리하세요.

## 테스트와 실행 확인

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m seoyoung_pos --demo --smoke-test
```

화면이 없는 Linux에서는 `QT_QPA_PLATFORM=offscreen`을 지정합니다. 스모크 테스트는 업무 DB 대신 임시 저장소로 Qt 화면과 데모 조회 경로를 확인한 뒤 종료합니다.

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m seoyoung_pos --demo --smoke-test
QT_QPA_PLATFORM=offscreen .venv/bin/python -m seoyoung_pos --demo --smoke-test --screenshot /tmp/seoyoung-pos.png
```

## Windows EXE 제작

**PyInstaller로 Windows EXE를 빌드하려면 Windows 64비트 환경이 필요합니다.** PyInstaller의 Linux 실행 결과는 Linux 실행 파일입니다. 위에서 안내한 Windows 런타임 포함 번들은 공식 Windows 구성요소를 Linux에서 조합하는 별도 방식입니다.

Windows PC에 Python 3.12 x64를 설치한 뒤 `build_windows.bat`를 실행합니다. 이 스크립트는 별도의 `.venv-build`를 만들고 버전이 고정된 의존성을 설치한 뒤 테스트와 빌드를 실행합니다. 처음 빌드할 때 인터넷이 필요합니다.

결과물:

```text
dist/
  SeoyoungPOS/
    SeoyoungPOS.exe
    _internal/
    README.md
  SeoyoungPOS-Windows-x64-portable.zip
  SeoyoungPOS-Windows-x64-portable.zip.sha256
```

`scripts/build.py`는 생성한 실행 파일로 스모크 테스트까지 진행합니다. 기존 배포 폴더에 업무용 `data`가 있으면 재빌드를 중단해 데이터 덮어쓰기를 방지합니다. 기존 배포 폴더를 다른 위치로 옮긴 뒤 새로 빌드하세요.

Linux에서 Windows 런타임 포함 번들을 재현하는 별도 도구는 `scripts/windows_portable.py`입니다. 이 방식과 Windows에서 실행하는 PyInstaller 빌드는 구성과 검증 범위가 다릅니다. Windows 번들 자체에는 `runtime`, `app`, `licenses`, `PORTABLE-BUNDLE.json`, 진단용 `diagnose.bat`가 포함되며, 자세한 명령은 [번들 제작 안내](docs/windows-portable-notes.md)를 확인하세요.

GitHub에서도 `.github/workflows/windows-build.yml`의 **Windows portable build**를 수동 실행할 수 있습니다. 완료된 실행의 Artifacts에서 프로그램 ZIP·소스 ZIP과 체크섬을 받습니다. 수동 실행은 공개 Release를 만들지 않습니다.

게시를 승인한 버전에 `v1.0.0`과 같은 `v*` 태그를 push하면, Windows에서 테스트·빌드·생성된 EXE 시작 검증을 모두 통과한 뒤 GitHub Releases에 ZIP을 게시합니다. 이후 PC의 웹 브라우저에서 해당 Release의 **Assets → SeoyoungPOS-Windows-x64-portable.zip**을 내려받을 수 있습니다. 게시 작업에만 저장소의 `contents: write` 권한이 부여됩니다. 이 워크플로 파일을 로컬에서 작성하거나 커밋한 것만으로 원격 빌드나 게시가 실행되는 것은 아닙니다.

Linux 개발용 독립 실행 파일이 필요하면 `.venv/bin/python scripts/build.py --native`로 해당 운영체제용 ZIP을 만들 수 있습니다. Linux 배포물은 Windows에서 실행할 수 없습니다. 빌드 PC보다 오래된 Linux에서는 glibc 호환성 때문에 실행이 제한될 수 있습니다.

## 사용 범위

이 버전은 단일 매장의 오프라인 매입·매출·재고 장부를 제공합니다. 여러 PC의 동시 접속, 서버 동기화, 결제 단말기와 저울의 하드웨어 연동, 법정 세무 신고 기능은 포함하지 않습니다. 사진에 있는 투게더포스의 원격지원·업데이트·광고·회원 마케팅 기능은 구현 범위에 포함하지 않았습니다.

PySide6/Qt, openpyxl, PyInstaller 등 외부 구성요소에는 각 프로젝트의 라이선스가 적용됩니다. 배포 전에 포함된 라이선스와 고지 사항을 확인하세요.
