"""Isolated, synthetic training records for the newly designed application."""
from datetime import date, timedelta


DEMO_CODE, DEMO_PASSWORD = "demo", "Standalone-Demo-2026!"


def ean(body):
    return body + str((-sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(body))) % 10)


def seed(store):
    if store.users_count():
        store.login(DEMO_CODE, DEMO_PASSWORD)
        return
    store.setup_admin(DEMO_CODE, "독립판 체험 관리자", DEMO_PASSWORD)
    today = date.today()
    supplier = store.save_partner({"kind": "supplier", "code": "S001", "name": "서영 한돈 유통", "contact": "샘플 담당자", "phone": "02-000-0000", "bank": "샘플은행", "account": "123-000-456", "opening_balance": 50000, "opening_date": (today - timedelta(days=4)).isoformat()})
    supplier2 = store.save_partner({"kind": "supplier", "code": "S002", "name": "한우 축산 공판장", "supplier_mode": "commission", "commission_bps": 500, "opening_date": today.isoformat()})
    customer = store.save_partner({"kind": "customer", "code": "C001", "name": "일반 매장 고객", "opening_date": today.isoformat()})
    member = store.save_member({"code": "M0001", "name": "김서영", "phone": "010-0000-1234", "memo": "실제 회원이 아닌 체험 자료"})
    store.adjust_points(member, 2000, "체험용 이전 포인트")
    catalog = [
        ("한돈 삼겹살", "돈육", "삼겹", 18000, 28000, "대한민국"),
        ("한돈 목살", "돈육", "목심", 16000, 24800, "대한민국"),
        ("한우 등심 1+", "한우", "등심", 68000, 108000, "대한민국"),
        ("한우 국거리", "한우", "국거리", 28000, 42000, "대한민국"),
        ("소 갈비살", "수입육", "갈비", 31000, 49800, "미국"),
        ("닭다리살", "계육", "정육", 7900, 12800, "대한민국"),
    ]
    products = []
    for index, (name, category, small, purchase, sale, origin) in enumerate(catalog, 1):
        products.append(store.save_product({"code": f"P{index:04d}", "barcode": ean("880" + f"{index:09d}"), "name": name, "receipt_name": name, "category": category, "category_mid": "냉장육", "category_small": small, "base_unit": "kg", "supplier_id": supplier if index < 3 else supplier2, "purchase_price": purchase, "sale_price": sale, "min_qty": "3", "origin": origin, "warehouse": "냉장 1창고", "shelf": f"A-{index:02}", "memo": "체험 자료 · 실제 영업 내역 아님"}))
    unit = store.save_unit({"product_id": products[0], "name": "500g 팩", "barcode": ean("880000000101"), "factor": "0.5", "purchase_price": 9000, "sale_price": 14000})
    for index, product in enumerate(products):
        price = catalog[index][3]
        store.post_document({"kind": "purchase", "date": (today - timedelta(days=2)).isoformat(), "partner_id": supplier if index < 2 else supplier2, "lines": [{"product_id": product, "qty": "12", "unit_price": price}], "paid": price * 3, "method": "transfer", "memo": "체험용 매입"})
    sale = store.post_document({"kind": "sale", "date": (today - timedelta(days=1)).isoformat(), "partner_id": customer, "member_id": member, "lines": [{"product_id": products[0], "qty": "1", "unit_price": 28000}], "paid": 28000, "method": "cash", "memo": "자동 포인트 체험"})
    source = store.document(sale)
    store.post_document({"kind": "sale_return", "date": today.isoformat(), "partner_id": customer, "source_id": sale, "lines": [{"product_id": products[0], "qty": "0.25", "source_line_id": source["lines"][0]["id"]}], "paid": 7000, "method": "cash", "memo": "원 전표에 연결된 부분 반품"})
    store.post_document({"kind": "sale", "date": today.isoformat(), "partner_id": customer, "lines": [{"product_id": products[0], "unit_id": unit, "qty": "1", "unit_price": 14000}, {"product_id": products[2], "qty": "0.5", "unit_price": 108000}], "paid": 60000, "method": "transfer"})
    store.save_draft({"kind": "purchase", "date": today.isoformat(), "partner_id": supplier, "lines": [{"product_id": products[1], "qty": "2", "unit_price": 16000}], "paid": 0, "memo": "입고 확인 전 보관 중인 초안"})
    store.save_promotion({"title": "한돈 주간 행사", "start": today.replace(day=1).isoformat(), "end": (today + timedelta(days=10)).isoformat(), "active": True, "items": [{"product_id": products[0], "sale_price": 26000}]})
    store.save_price_schedule({"product_id": products[1], "date": (today + timedelta(days=7)).isoformat(), "title": "다음 주 목살 판매가", "sale_price": 25800})
    store.save_gift({"code": "G001", "name": "보냉 가방", "points": 1000, "stock": 20, "active": True})
    product = next(r for r in store.products() if r["id"] == products[0])
    store.create_count({"title": "냉장고 실사 초안", "date": today.isoformat(), "items": [{"product_id": products[0], "expected_qty": product["stock_qty"], "counted_qty": product["stock_qty"]}]})
