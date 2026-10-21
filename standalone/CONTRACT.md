# 새 독립판 구현 계약

## 2.3.0rc1 현재 계약 (아래 초기 계약보다 우선)

스키마는 208이며 200~207의 정확한 과거 구조도 검증·이관한다. DB 금액은 **0.01원 정수**, 공개 금액은 Decimal 원이다. `currency.py`의 경계 변환은 중첩 API에서 중복 수행하지 않는다. 기존 원 정수 장부는 보호 백업 후 100배 이관하고 수량은 변경하지 않는다. 새 g 상품의 단가 기준은 100g이며 각 전표의 반올림 정책·단위·단가 스냅샷을 보존한다.

공급사 그룹/프로필, 로컬 판매 서식/보고서, 개인 일정의 양·음력 반복 규칙과 발생별 알림 영수증, 개인 테마/효과음을 포함한다. 일기·가계부·성장/건강 기록은 계정별 데이터키로 AES-GCM 저장하며 업무 장부와 분리한다. 로그인 최초 공개 암호는 GUI 진입 전에 사용자 암호로 교체하며 일기장은 별도 암호 필수, 가계부는 별도 암호 선택이다. 이메일 복구는 명시적 발송·최초 주소 인증·개인 복구키의 사전 등록을 요구한다. SMTP는 현재 Windows 사용자 DPAPI로 보호한다. 원격 정지/자동 복사 추적은 없다.

아래는 초기 엔진 구조와 2.2 이전 API 이력이다. 금액·스키마 버전은 위 현재 계약을 적용한다.

기존 `seoyoung_pos`의 소스·DB·화면 클래스를 가져오거나 import하지 않는다. 이 디렉터리의 `pos2` 패키지는 PDF의 오프라인 업무 흐름에서 새로 설계한다. 기존 프로그램과 데이터는 그대로 둔다. 새 업무 DB는 `data-v2/seoyoung-standalone-v2.db`, 데모는 별도 임시/데모 파일이다.

## 공통 엔진

`Store(path)`는 CatalogMixin, CommerceMixin, OperationsMixin, LoyaltyMixin을 합성한다. 공개 계정은 `store.actor`(id/code/name/role/permissions/active), 로그아웃은 None. `store.db`: sqlite3.Row 연결, WAL/FK/FULL, `_tx()` BEGIN IMMEDIATE 원자 트랜잭션, `_require(permission)` 최신 권한 재조회, `_audit(action,entity,id,detail)` 동일 트랜잭션 JSON 기록. 중첩 `_tx()` 금지: 모듈 내부 `_...` 훅만 같은 트랜잭션에서 호출한다. `permissions`: catalog,trade,inventory,loyalty,reports,admin. 관리자 전체; 사용자/설정 admin 전용.

수량은 기본단위의 1/1000 정수 저장, 공개 `qty_text`는 소수 3자리 문자열. 금액은 정수 원, 각 행 ROUND_HALF_UP. 공개 저장 API 수량 입력은 문자열/Decimal이며 직접 정수 스케일값을 넘기지 않는다. `common.py`의 `qty(value,allow_zero=False,signed=False)`, `money(value,positive=False)`, `day(value)`, `qtext(scaled)`, `rounded(Decimal)` 공통 사용. 금액·스케일 수량 상한 9e12.

## 핵심 테이블(기초 담당자가 schema.py에 작성)

- users: id,code,name,password_hash,role,permissions,active
- partners: id,kind(supplier/customer),code,name,business_no,contact,phone,bank,account,account_holder,memo,active,opening_balance,opening_date
- products: id,code,barcode,name,receipt_name,category,category_mid,category_small,specification,base_unit,tax_mode(exempt/taxable),tracked,active,supplier_id,purchase_price,sale_price,min_qty,stock_qty,stock_cost,origin,warehouse,shelf,keywords,memo,created_at,updated_at
- product_units: id,product_id,name,barcode,factor(1000=기본단위1),purchase_price,sale_price,active
- documents: id,number,kind(purchase/sale/purchase_return/sale_return),date,status(draft/posted/cancelled),partner_id,member_id,source_id,total,cash_paid,points_used,points_earned,memo,user_id,created_at,cancel_reason
- document_lines: id,document_id,product_id,unit_id,product_name,unit_name,factor,input_qty,base_qty,unit_price,total,cost,source_line_id
- payments: id,partner_id,document_id,date,amount(정상 지급/수금+, 반품 환불-),method(cash/transfer),memo,voided,user_id,created_at
- stock_events: id,product_id,document_id,date,kind,qty_delta,cost_delta,balance_qty,balance_cost,reason,user_id,created_at
- audit: id,at,user_id,action,entity,entity_id,detail
- settings: key,value(JSON 문자열)

운영·회원의 추가 테이블은 담당 모듈 `_init_operations()`/`_init_loyalty()`가 CREATE IF NOT EXISTS로 만든다. Store.__init__ 호출 순서는 schema → loyalty → operations. 기존 DB는 열지 않으며 기존 코드의 메타데이터/스키마를 복사하지 않는다.

## API

2.2.0: `permissions.py`의 MENU_POLICIES와 `deny:메뉴`, `deny:메뉴.작업`은 기존 영역 권한 위에 메뉴별 접근·등록·수정·삭제 제한을 적용한다. `Store.require_menu`/`_require_capability`는 최신 계정을 재조회하고 공개 쓰기 API의 트랜잭션 안에서 검사한다. 기존 업무영역 권한의 부재는 세부 허용으로 우회할 수 없으며 관리자는 전체 권한이다. 권한 메뉴는 관리자만 변경하고 JSON allowlist로 미지의 권한을 거부한다. 현재 스키마 버전은 202이며 200/201 백업도 검사·이관한다. 배포 ZIP 이름은 패키지 버전에서 자동 생성한다.

`backup_schedule.py`는 관리자 설정을 검증하고 실행 중 일정 확인/누락 1회 보충/종료 백업을 고정 폴더로 수행한다. 직원도 고정 자동 백업만 가능하며 임의 경로·복원 권한은 없다. 성공 후에만 일정 완료 표시, 실패는 5분 재시도 간격, 부분 파일은 목록·정리에서 제외한다. 일정은 현지 PC 시각, 상태는 장부 외부 sidecar에 저장한다. `navigation.py`는 미저장 확인 후 초안 저장 또는 폐기를 수행하며 저장 실패 시 이동을 막는다. 메뉴 도움말은 고정 한글 문자열이며 외부 조회가 없다.

2.1.0 추가: `categories(),save_category(data,id=None),delete_category(id)`는 최대 3단계 마스터와 사용 중 삭제 방어를 제공한다. `save_product` 새 코드 공란은 `code_sequences`의 영속 최대값으로 원자 생성하며 복원 시에도 라이브 최대값을 유지한다. `retirement_target`는 퇴출대상 표시(거래 가능), `active=0`는 무효이다. UI에서는 사전에 만든 분류만 선택한다. `products` 검색은 규격을 포함한다.

`SettlementMixin`: `supplier_summary(start,end,search='',only_purchases=False,partner_id=None)`, `supplier_outstanding(partner_id,payment_date=None)`, `settle_supplier(partner_id,amount,date,method='cash',memo='',expected_state=None)`, `supplier_payment_history(start,end,partner_id=None,include_voided=True)`, `supplier_settlement_detail(id)`, `void_supplier_settlement(id,reason)`, `void_supplier_payment(id,reason)`. 새 supplier_settlements는 opening_amount와 payments.supplier_settlement_id로 초기 외상·전표별 지급을 연결하고 이중 집계하지 않는다. 한 트랜잭션에서 날짜·현재잔액·스냅샷·마감을 재확인해 배분하며 오류는 전체 롤백한다. 묶음 일부 결제의 직접 취소는 막고 당일 묶음 전체 취소만 허용한다.

`RecoveryMixin`/`BackupPolicyMixin`: `create_backup(before_restore=False),backup_files(),inspect_backup(path),restore_backup(path,password,expected_digest=None),run_backup_retention(now_at=None)`. 관리 백업은 data-v2/backups, 주간 상태는 DB 밖 .retention.json에 원자 기록한다. 최근 15개 관리 파일은 유지하며 7일마다만 초과분을 삭제한다. 복원은 200/201 스키마와 전체 SQLite 무결성·FK·활성 관리자를 확인한 스테이징 사본을 사용하고, 먼저 보호 백업을 만든다. SQLite backup API의 트랜잭션과 실패 롤백으로 교체하고 복원 토큰으로 다른 연결의 세션을 무효화한다. GUI는 QLockFile로 같은 장부의 중복 실행을 막고 복원 완료 후 종료한다. schema 초기화 후 사용자 버전은 201이다.

Catalog: `users_count, setup_admin(code,name,password), login(code,password), logout, list_users, save_user(data,id=None), delete_user(id), change_password(old,new)`; `partners(kind,search=''),save_partner(data,id=None),delete_partner(id)`; `products(search='',supplier_id=None,category='',active_only=False),save_product(data,id=None),delete_product(id)`; `units(product_id),save_unit(data,id=None),delete_unit(id), lookup_barcode(barcode), bulk_category(ids,category)`; `settings(),save_settings(dict),audit_log(),backup(path)`. 공개 product에는 stock_qty/min_qty 문자열과 base_unit, stock_cost 원가액; units.factor는 공개 문자열. `lookup_barcode`→{product,unit:null|row}. 기본단위 변경은 모든 이력/확장단위가 있으면 거부.

Commerce: `documents(kind=None,start='',end='',partner_id=None,status='',search='')`; `document(id)` includes lines/payments; `save_draft(data,id=None)`; `post_document(data,draft_id=None)`→id. data={kind,date,partner_id,member_id,source_id,lines:[{product_id,unit_id|null,qty,unit_price,source_line_id|null}],paid,method:'cash'|'transfer',points_used,memo}. `draft_id` 게시 전 상태를 재확인. 반품은 원전표·원행 기준 부분수량 상한, 비례 원가 복원, 금액은 원단가 기준(임의 환불단가 금지). `add_payment(document_id,amount,date,method='cash',memo='')`, `void_payment(id,reason)`, `cancel_document(id,reason)`, `delete_draft(id)`, `ledger(partner_id,start='',end='')` → {opening,charge,payment,closing,entries:[date,kind,number,charge,payment,balance,memo]}. 초기 외상은 거래처 opening_balance/date에 반영. `quote(product_id,date,unit_id=None,member_id=None)` → {price,purchase_price,source}; 기본가를 바꾸지 않는 제안가. 실재 전표 수정은 초안만, 확정은 취소 후 재등록 정책을 명시.

Commerce 재고는 `_move(product_id,qty_delta,cost_delta,kind,reason,document_id=None,date=None)`(스케일 정수 인수) 동일 트랜잭션에서 호출. tracked=False는 재고 이동/부족검사 제외. 제품·회원·거래처 사용여부 검사. 원가는 등록순 이동평균, 새 반품은 원행 원가 비례. 확장단위의 입력×factor를 기본단위 천분율로 정확히 환산(3자리 초과면 거부).

Operations: `create_count(data)`→id (data={title,date,items:[{product_id,expected_qty,counted_qty}]}), `counts()`, `count(id)`, `apply_count(id)`(초안→확정, 변경된 장부 차단), `delete_count(id)` 초안만. `stock_events(product_id=None)`; `inventory_close(month)`→id, `inventory_closes()`, `inventory_close_detail(id)`; `cash_close(data)`→id data={date,opening_cash,counted_cash,memo}, `cash_closes()`, `cash_expected(date)`; `report(start,end,group='day')`→{rows,totals}, group=day/month/product/category/supplier/member. 수량은 단위별 분리; 보고서 반품·취소 반영, points와 cash 구분. 그룹행 label,unit,purchase_qty,sale_qty,purchase_total,sale_total,cost,profit. 집계 해당 월 마감은 실제 event 날짜 기준으로 음수/미래 스냅샷 금지, 월 마감 이후 전기일자 이동은 `_assert_open(date)`로 검사(Commerce도 이동 전 호출).

Loyalty: `members(search=''),save_member(data,id=None),delete_member(id),point_history(member_id),adjust_points(member_id,delta,reason)`; `promotions(),promotion(id),save_promotion(data,id=None),delete_promotion(id),clone_promotion(id,new_start,new_end),extend_promotion(id,new_end)` data={title,start,end,active,items:[{product_id,purchase_price|null,sale_price|null}]}. `member_prices(member_id),save_member_price(data),delete_member_price(id)`, `price_schedules(),save_price_schedule(data)`; `gifts(),save_gift(data,id=None),redeem_gift(member_id,gift_id,qty,reason),gift_history(member_id=None)`. `quote` 구현도 Loyalty 담당: 날짜별 예약가격/특매/회원지정가를 결정하고 각 source를 표시. 확장단위는 별도 등록단가(일반 기본가 행사 자동환산 금지) 명시. 원거래 연결 포인트 `_sale_points(document_id,member_id,total,points_used)`→earned; `_reverse_sale_points(document_id,source_document_id,return_total)`→(restored_used,reversed_earned), 같은 _tx 내 실행, 잔액 음수 금지. 정책 settings 기본값 earn_bps=100,point_min=1000,point_step=100,point_enabled=true. member_id 매출은 완전 정산만 허용하여 포인트를 미결제 매출에 먼저 지급하지 않음. 반품시 복원/회수는 누적 반환비율 기준 차액으로 마지막 반품에 반올림 잔여 전부 정산.

## UI 분담

공통 `pos2/widgets.py` 루트 담당: `Page(window,title,description)` + `.store`, `.body` QVBoxLayout, `.actions` QHBoxLayout, `.table(headers)` DataGrid 생성, `.notify(text)`. `DataGrid(headers)` has `.fill(rows,records=None)` `.selected()` `.export_rows()`. `FormDialog(title,parent=None)` has `.body`, `.form` QFormLayout, `.field(key,label,value='',password=False)` returnsQLineEdit, `.combo(key,label,choices,current=None)` returnsQComboBox choices=[(label,data)], `.finish(callback)` Save/Cancel, `.error(exc)`. `.fields`dict. 숫자표시는 `won`, `amount`, `date_field`. `.store.actor` 권한으로 메뉴/작업 제어. `window.open_page(key)`, `.new_trade(kind)`.

CatalogUI own `catalog_ui.py`: ProductsPage + ProductDialog(상세탭 상품/매입/판매/재고/변경/확장단위), PartnersPage(kind), UsersPage, SettingsPage. Commodity prices/qty read-only summaries comma formatting. 기존 UI를 import하지 않음.

WorkflowUI own `workflow_ui.py`: TradesPage(kind), TradeDialog, LedgerPage, CountsPage, ReportPage, ClosingsPage. Root own `loyalty_ui.py`, `app.py` shell/login/demo/CLI + docs + fresh packaging.

카드/VAN/현금영수증 승인, SMS/센터/온라인 상품마스터/매장동기화/원격지원/자동업데이트, 전용 핸드터미널·저울 통신 프로토콜은 제외한다. 원본 설명서 문구/로고/이미지를 복제하지 않는다.

최신 사용자 요청을 반영해 엑셀 저장·일반 프린터 인쇄·라벨 인쇄는 필수로 구현한다. 일반 인쇄는 Qt PrintSupport와 Windows 드라이버/인쇄 미리보기, 라벨은 사용자 지정 용지(기본 60×40mm)·위치·매수와 Code128/EAN13을 지원한다. USB 리더기는 사용자가 확인한 키보드 입력(HID) 방식이며 Enter/Tab을 스캔 완료로 처리하되 전표 저장·확정을 유발하지 않는다. 제조사 전용 원시 프린터 명령은 사용하지 않는다. 물리 장치가 없는 환경에서 실기기 출력을 검증했다고 주장하지 않는다.
