"""Optional sample data; always placed in a separate demo database."""
from datetime import date, timedelta


def populate_demo(service):
    if service.users_count():
        service.login("demo", "Demo-2026!")
        return
    service.create_initial_admin("demo", "서영 관리자", "Demo-2026!")
    service.login("demo", "Demo-2026!")
    supplier_ids = []
    for code, name, contact, phone in [
        ("S001", "정미트 (청록정육)", "김정훈", "02-3425-1800"),
        ("S002", "미소한우 유통", "박미소", "031-8021-2400"),
        ("S003", "서영 축산물공판장", "이서영", "032-552-8100"),
        ("S004", "우리농장 직거래", "최우진", "010-4250-6020"),
    ]:
        supplier_ids.append(service.save_partner({"kind": "supplier", "code": code, "name": name, "contact": contact, "phone": phone, "business_no": "", "bank": "", "account": "", "account_holder": "", "memo": "데모 거래처"}))
    customer_ids = []
    for code, name, phone in [("C001", "한상 정육식당", "02-521-4420"), ("C002", "오늘의 식탁", "031-207-5180"), ("C003", "우리동네 고깃집", "02-419-8070")]:
        customer_ids.append(service.save_partner({"kind": "customer", "code": code, "name": name, "phone": phone, "memo": "데모 거래처"}))
    products = [
        ("P001", "203203", "돼지 삼겹살", "돈육", "국내산 · 냉장", "대한민국", 18800, 29800, "8", 0),
        ("P002", "203204", "돼지 목살", "돈육", "국내산 · 냉장", "대한민국", 16200, 24800, "6", 0),
        ("P003", "203205", "돼지 앞다리살", "돈육", "국내산 · 냉장", "대한민국", 8600, 13800, "5", 2),
        ("P004", "203206", "돼지 갈비", "돈육", "국내산 · 냉장", "대한민국", 12400, 19800, "5", 0),
        ("P005", "204101", "한우 등심 1+", "한우", "1+등급 · 구이용", "대한민국", 68000, 108000, "4", 1),
        ("P006", "204102", "한우 안심", "한우", "1등급 · 냉장", "대한민국", 82000, 128000, "3", 1),
        ("P007", "204103", "한우 국거리", "한우", "1등급 · 절단", "대한민국", 28000, 42000, "5", 1),
        ("P008", "205201", "소 부채살", "수입육", "프라임 · 냉장", "미국", 22400, 36800, "5", 2),
        ("P009", "205202", "소 갈비살", "수입육", "초이스 · 냉장", "미국", 31000, 49800, "4", 2),
        ("P010", "206301", "닭 다리살", "계육", "정육 · 냉장", "대한민국", 7900, 12800, "6", 3),
        ("P011", "206302", "오리 로스", "기타", "슬라이스 · 냉장", "대한민국", 11400, 18800, "4", 3),
        ("P012", "203207", "돼지 항정살", "돈육", "특수부위 · 냉장", "대한민국", 24500, 39800, "4", 0),
    ]
    ids = []
    for code, barcode, name, category, spec, origin, buy, sell, minimum, supplier_index in products:
        ids.append(service.save_product({"code": code, "barcode": barcode, "name": name, "category": category, "specification": spec, "unit": "kg", "origin": origin, "supplier_id": supplier_ids[supplier_index], "purchase_price": buy, "sale_price": sell, "min_stock": minimum, "memo": "실제 거래가 아닌 데모 자료입니다.", "active": True}))
    today = date.today()
    for i, product in enumerate(products):
        buy = product[6]
        quantity = "3.500" if i in (5, 11) else str(25 + i * 2)
        service.create_document("purchase", supplier_ids[product[9]], (today - timedelta(days=12 - i % 8)).isoformat(), [{"product_id": ids[i], "qty": quantity, "unit_price": buy}], paid=0, memo="샘플 입고 · 실제 거래 아님")
    for day in range(7):
        items = [{"product_id": ids[day % 5], "qty": f"{day + 1}.250", "unit_price": products[day % 5][7]}, {"product_id": ids[7], "qty": "1.500", "unit_price": products[7][7]}]
        service.create_document("sale", customer_ids[day % 3], (today - timedelta(days=6 - day)).isoformat(), items, paid=10000 if day % 2 else 0, memo="샘플 출고 · 실제 거래 아님")
