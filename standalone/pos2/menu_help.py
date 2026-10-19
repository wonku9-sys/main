"""Short Korean hover help for offline business menus and common actions."""
from PySide6.QtWidgets import QProxyStyle, QStyle


MENU_HELP = {
    "home": "업무 첫화면으로 이동합니다. 저장하지 않은 입력이 있으면 먼저 확인합니다.",
    "diary":"로그인 후 별도 일기장 암호로 잠금을 해제합니다. 제목·본문은 암호화 저장되며 5분 동안 사용하지 않으면 잠깁니다.",
    "worklog":"내 업무일지를 날짜별로 작성·검색하고 인쇄·엑셀 저장합니다. 보안 일기장과 달리 별도 암호화하지 않습니다.",
    "household":"개인 수입·지출·잔액을 관리합니다. 매장 장부와 분리되며 별도 암호를 선택할 수 있습니다.",
    "products": "상품코드·바코드·상품명·규격으로 검색하고 상품과 확장단위를 관리합니다.",
    "categories": "대·중·소분류를 관리합니다. 항목을 오른쪽 클릭하면 추가·수정·삭제할 수 있습니다.",
    "suppliers": "매입 공급사의 연락처·계좌와 초기 외상잔액을 관리합니다.",
    "customers": "판매처의 기본정보와 초기 미수잔액을 관리합니다.",
    "labels": "상품 바코드 라벨을 미리 보고 Windows 프린터로 출력합니다. 용지 크기를 지정할 수 있습니다.",
    "purchases": "기간·공급사·매입/반품 유형으로 매입전표를 조회하고 매입등록을 시작합니다.",
    "purchase_suppliers": "기간과 공급사별 매입·반품·순매입을 조회하고 엑셀 저장·인쇄합니다.",
    "purchase_categories": "대·중·소분류별 매입·반품 금액과 g 기준 수량을 조회합니다.",
    "purchase_products": "상품코드·바코드·상품명·규격으로 단품별 매입 실적을 찾습니다.",
    "purchase_documents": "기간 내 전표별 매입·반품을 조회하고 더블클릭해 원전표를 봅니다.",
    "purchase_statement": "공급사별 과세·면세·포함 부가세를 내부 관리용으로 집계합니다. 전자세금계산서 발급은 하지 않습니다.",
    "payments": "공급사별 미지급잔액·거래·결제 이력을 조회하고 부분 지급을 기록합니다. 당일 결제는 취소할 수 있습니다.",
    "sales": "매출전표와 고객반품을 조회하고 판매·수금 내역을 기록합니다.",
    "ledger": "거래처의 기간 전 이월·거래·입출금과 누적잔액을 확인합니다.",
    "inventory": "상품별 현재고와 입출고 이력, 이동평균 원가를 조회합니다.",
    "counts": "실제 재고를 초안으로 입력하고 차이를 검토한 뒤 장부에 반영합니다.",
    "closings": "담당자별 현금과 월말 재고를 확인하고 마감합니다.",
    "members": "회원정보·포인트 내역·회원별 지정가격을 관리합니다.",
    "promotions": "기간과 대상 상품을 정해 특매가격을 적용합니다.",
    "prices": "지정한 날짜부터 적용할 상품가격 변경을 예약합니다.",
    "gifts": "사은품을 등록하고 회원의 포인트 교환 내역을 기록합니다.",
    "overview": "이번 달 확정 매입·매출·매출총이익을 한눈에 확인합니다.",
    "reports": "기간별 일·월·상품 상세 집계를 조회하고 엑셀 저장·인쇄합니다.",
    "commission": "수수료 공급사의 판매실적과 수수료 정산액을 확인합니다.",
    "users": "관리자가 사용자 계정과 역할을 관리합니다. 현재 계정과 마지막 관리자는 삭제할 수 없습니다.",
    "permissions": "직원별 메뉴 접근·등록·수정·삭제 권한을 설정합니다. 저장 즉시 다음 작업부터 적용됩니다.",
    "settings": "매장정보·자동 백업 일정을 설정하고 백업 목록에서 자료를 복원합니다.",
}
from .offline_menus import REPORT_VIEWS, SALES_VIEWS, BASIC_VIEWS, MEMBER_VIEWS, FORM_VIEWS
MENU_HELP.update({key: f"{value[0]} 기준으로 확정 전표·반품을 집계하고 엑셀·인쇄합니다. 날짜·공급사·분류·상품으로 찾을 수 있습니다." for key,value in {**REPORT_VIEWS,**SALES_VIEWS}.items()})
MENU_HELP.update({key: f"{title} 자료를 검색·인쇄·엑셀 저장합니다. 이력은 기록된 당시 내용을 보존합니다." for key,title in BASIC_VIEWS.items()})
MENU_HELP.update({key: f"{title}를 기간·회원으로 조회하고 인쇄·엑셀 저장합니다." for key,title in MEMBER_VIEWS.items()})
MENU_HELP.update({key: f"{value[0]}를 저장하고 인쇄·PDF·엑셀로 출력합니다. 재고와 결제를 변경하지 않으며 전자세금계산서를 발급하지 않습니다." for key,value in FORM_VIEWS.items()})
ACTION_HELP = {
    "첫화면": MENU_HELP["home"], "상품장": MENU_HELP["products"],
    "매입전표": MENU_HELP["purchases"], "매입등록": "공급사를 선택한 뒤 상품·수량·매입가격을 입력합니다. 반품도 같은 전표 창에서 선택합니다.",
    "매입 등록": "공급사를 선택해 새 매입전표를 작성합니다.",
    "판매 등록": "판매처와 상품을 선택해 새 매출전표를 작성합니다.",
    "F8 스캔": "바코드 입력칸으로 이동합니다. USB 키보드형 스캐너로 읽고 Enter를 입력하세요.",
    "조회": "지정한 기간과 검색 조건으로 목록을 다시 불러옵니다.",
    "엑셀 저장": "현재 조회 중인 표를 Excel 파일로 저장합니다.",
    "인쇄": "현재 표를 미리 보고 Windows에 등록된 프린터로 출력합니다.",
    "결제 처리": "선택한 공급사에 실제 지급한 금액을 기록합니다. 일부 금액도 입력할 수 있으며 실제 송금은 하지 않습니다.",
    "선택 결제 취소": "당일 결제를 취소하고 미지급잔액을 되돌립니다. 취소 사유와 이력은 남습니다.",
    "지금 백업": "현재 장부 전체를 전용 backups 폴더에 즉시 백업합니다.",
    "선택한 백업 적용": "선택한 백업으로 전체 자료를 교체합니다. 현재 자료를 먼저 보호 백업하고 관리자 확인을 거칩니다.",
    "설정 저장": "매장정보·포인트 정책·자동 백업 일정을 저장합니다.",
    "권한 저장": "선택한 직원의 메뉴별 권한을 저장합니다.",
    "초안 저장": "입력 중인 전표를 보관합니다. 재고와 결제에는 아직 반영하지 않습니다.",
    "저장": "작성한 전표를 확인한 뒤 재고·결제에 반영합니다.",
    "반품등록": "원매입전표를 선택해 반품합니다. 남은 반품 가능 수량과 원래 단가를 적용합니다.",
    "공급사 검색": "공급사명이나 공급사코드로 거래처를 찾습니다.",
    "관리자 설정": MENU_HELP["settings"],
    "비밀번호 변경": "현재 비밀번호를 확인한 뒤 내 로그인 비밀번호를 변경합니다.",
    "로그아웃": "작업 저장과 종료 백업을 확인한 뒤 프로그램을 종료합니다.",
}


def attach_help(widget, text):
    if text:
        widget.setToolTip(text)
        widget.setStatusTip(text)
        if hasattr(widget, "setToolTipDuration"):
            widget.setToolTipDuration(8000)
    return widget


class MenuHelpStyle(QProxyStyle):
    def __init__(self):
        super().__init__("Fusion")

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
            return 700
        if hint == QStyle.StyleHint.SH_ToolTip_FallAsleepDelay:
            return 300
        return super().styleHint(hint, option, widget, returnData)
