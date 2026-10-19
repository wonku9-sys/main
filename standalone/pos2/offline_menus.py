"""PDF menu names retained where the standalone data model can fulfil them."""

REPORT_VIEWS = {}
for period, prefix in (("day", "일"), ("month", "월")):
    for group, label in (("summary", "별 종합"), ("category", "-분류별"), ("product", "-단품별"), ("supplier", "-공급사별"), ("tax", "-분류별과면세"), ("commission", "-수수료공급사별")):
        REPORT_VIEWS[f"report_{period}_{group}"] = (prefix + label, period, group, "reports")

SALES_VIEWS = {
    "sales_realtime": ("판매조회-실시간", "day", "product", "trade"),
    "sales_category": ("판매조회-분류별", "day", "category", "trade"),
    "sales_supplier": ("판매조회-공급사별", "day", "supplier", "trade"),
    "sales_product": ("판매조회-단품별", "day", "product", "trade"),
    "sales_daily": ("일별조회", "day", "summary", "trade"),
    "sales_monthly": ("월별조회", "month", "summary", "trade"),
}
MEMBER_VIEWS = {
    "member_best": "베스트회원", "member_points": "포인트 조회·조정",
    "member_transactions": "회원 거래내역", "member_prices": "회원지정가",
    "gift_history": "사은품 지급조회",
}
BASIC_VIEWS = {
    "product_units": "확장단위", "retirement": "퇴출대상", "weighted_products": "저울상품",
    "product_changes": "상품변경로그", "user_access": "직원접속로그",
}
FORM_VIEWS = {"quotations": ("견적서", "quotation"), "statements": ("거래명세서", "statement"), "member_tax": ("(세금)계산서 참고자료", "tax_reference")}
