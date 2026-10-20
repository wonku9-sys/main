"""Data-only purchase spreadsheets: drafts only, never stock/payment."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
import re
from .catalog_import import read_excel
from .common import day, money
from .currency import public_input, round_amount


def key(value):
    return re.sub(r'[\s/·_()\n]+', '', str(value)).casefold()


ALIASES = {
    'code': {'코드바코드', '상품코드', '바코드', '코드'},
    'name': {'상품명', '품명'}, 'qty': {'수량', '매입량', '매입수량'},
    'unit_price': {'단가', '매입가', '매입단가'}, 'unit': {'단위'},
    'total': {'금액', '매입금액'}, 'tax': {'과면세', '과세면세'},
    'supplier': {'공급사', '공급사명'},
}


def classify_rows(rows):
    headers = {key(v) for row in rows[:1] for v in row if str(v).strip()}
    if {'입고일시', '매입합계'} <= headers:
        return '매입리스트 · 전표 요약 (상품 상세 없음)'
    if {'공급사명', '사업자번호', '계좌번호'} <= headers:
        return '공급사 목록'
    if {'전표상태', '처리일자', '잔액'} <= headers:
        return '공급사 거래원장 · 결제/잔액 집계'
    if '매입합계' in headers and ('과세매입' in headers or '면세매입' in headers):
        return '공급사별 매입 집계'
    if '매출액' in headers and '상품명' in headers:
        return '단품별 판매 집계'
    if {'단말', '등록시각', '거래금액'} <= headers:
        return '단말 보류 내역'
    if '일日' in headers:
        return '달력 집계'
    if '수량' in headers and '바코드' in headers:
        return '매입 상품 상세' if '매입단가' in headers or '단가' in headers else '바코드·수량 목록 (단가 없음)'
    return '일반 매입 양식'


def plan_files(paths, catalog, default_supplier=None, default_date=None, use_current_prices=False):
    codes, names = defaultdict(list), defaultdict(list)
    for product in catalog['products']:
        for value in {product['code'], product['barcode'], *product.get('unit_barcodes', [])} - {''}:
            codes[value].append(product)
        names[product['name']].append(product)
    result = []
    for path in paths:
        entry = dict(file=Path(path).name, error='', lines=[], source_hash='')
        try:
            rows = read_excel(path)
            entry['format'] = classify_rows(rows)
            if entry['format'] in {'매입리스트 · 전표 요약 (상품 상세 없음)', '공급사 목록', '공급사 거래원장 · 결제/잔액 집계', '공급사별 매입 집계', '단품별 판매 집계', '단말 보류 내역', '달력 집계'}:
                raise ValueError(entry['format']+' 파일입니다. 매입 품목으로 등록하지 않습니다. 품목이 있는 매입전표 파일을 선택하세요.')
            entry['source_hash'] = sha256(Path(path).read_bytes()).hexdigest()
            formatted = bool(rows and key(rows[0][0]) == '매입전표')
            if rows and '반품' in str(rows[0][0]):
                raise ValueError('반품은 원매입 연결이 필요하므로 별도 반품등록을 이용하세요.')
            if formatted and len(rows) > 2 and '취소' in ' '.join(rows[1]):
                raise ValueError('취소 전표 파일은 불러올 수 없습니다.')
            header_index, columns = None, {}
            for index, row in enumerate(rows[:50]):
                found = {field: next((i for i, cell in enumerate(row) if key(cell) in aliases), None) for field, aliases in ALIASES.items()}
                if found['qty'] is not None and (found['name'] is not None or found['code'] is not None):
                    header_index, columns = index, found
                    break
            if header_index is None:
                raise ValueError('상품명(또는 바코드)·수량 제목 행이 필요합니다.')
            legacy = columns['qty'] is not None and columns['qty']+1 < len(rows[header_index]) and not str(rows[header_index][columns['qty']+1]).strip() and columns['unit_price'] is not None
            if legacy:
                columns['unit'] = columns['qty']+1
            if columns['unit_price'] is None and not use_current_prices:
                raise ValueError('파일에 단가가 없습니다. 현재 등록 매입가를 사용하려면 상단 옵션에 동의 후 다시 불러오세요. 과거 거래 단가로 간주하지 않습니다.')
            supplier_name, business_no, date = '', '', day(default_date)
            if formatted:
                supplier_name = rows[4][1] if len(rows) > 4 and len(rows[4]) > 1 else ''
                business_no = rows[3][1] if len(rows) > 3 and len(rows[3]) > 1 else ''
                match = re.search(r'매입일:\s*(\d{4}-\d{2}-\d{2})', ' '.join(rows[1]))
                if match:
                    date = day(match.group(1))
            def suppliers(name, number=''):
                return [p for p in catalog['suppliers'] if p['active'] and
                        (p['business_no'] == number if number else p['name'] == name)]
            supplier_id = None
            if supplier_name or business_no:
                matches = suppliers(supplier_name, business_no)
                if len(matches) != 1:
                    raise ValueError('파일의 공급사를 유일하게 찾지 못했습니다. 공급사명·사업자번호를 확인하세요.')
                supplier_id = matches[0]['id']
            elif legacy or entry['format'] == '바코드·수량 목록 (단가 없음)':
                match = re.match(r'^.*?전표_(.+)_(\d{4}-\d{2}-\d{2})[ T]\d{2}[-:]\d{2}', Path(path).name)
                if match:
                    hint, date_hint = match.groups()
                    matched = suppliers(hint.strip())
                    date = day(date_hint)
                    if len(matched) == 1:
                        supplier_id = matched[0]['id']
                        entry['metadata_source'] = '공급사·날짜: 파일명에서 추출 (확인 필요)'
                    elif not default_supplier:
                        raise ValueError('파일명 공급사를 찾지 못했습니다. 기본 공급사를 선택하거나 공급사를 먼저 등록하세요.')
            for index, row in enumerate(rows[header_index+1:], header_index+2):
                def cell(field):
                    column = columns.get(field)
                    return str(row[column]).strip() if column is not None and column < len(row) else ''
                name = cell('name')
                if (not name and not cell('code')) or name in {'소계', '합계', '총계', '전표 총합계'}:
                    continue
                if formatted and not str(row[0]).strip().isdigit():
                    continue
                if len(entry['lines']) >= 2000:
                    raise ValueError('전표 한 개당 최대 2,000개 품목입니다.')
                try:
                    matches = codes.get(cell('code'), []) if cell('code') else names.get(name, [])
                    if len(matches) != 1:
                        raise ValueError('상품코드/바코드 또는 유일한 상품명으로 상품을 찾을 수 없습니다.')
                    product = matches[0]
                    if not product['active']:
                        raise ValueError('무효 상품입니다.')
                    quantity = Decimal(cell('qty').replace(',', ''))
                    if quantity < 0:
                        raise ValueError('음수 수량은 반품입니다. 원매입전표를 선택한 별도 반품등록을 이용하세요.')
                    price = public_input(cell('unit_price').replace(',', '')) if columns['unit_price'] is not None else product['purchase_price']
                    if not quantity.is_finite() or quantity <= 0 or quantity*1000 != (quantity*1000).to_integral_value():
                        raise ValueError('수량은 양수이며 소수점 셋째 자리까지 입력하세요.')
                    tax = {'과': 'taxable', '과세': 'taxable', '면': 'exempt', '면세': 'exempt'}.get(cell('tax'))
                    if tax and tax != product['tax_mode']:
                        raise ValueError('파일 과면세와 상품 등록정보가 다릅니다. 상품 정보를 먼저 확인하세요.')
                    raw_unit = cell('unit').replace(' ', '')
                    raw_unit = re.sub(r'\(×[^)]+\)$', '', raw_unit)
                    gram = product['base_unit'] == 'kg' and raw_unit in {'g', 'g(100g당)', 'g(100g당·kg환산)'}
                    unit_id = None
                    barcode_units = [u for u in catalog['units'] if u['product_id'] == product['id'] and u.get('barcode') == cell('code') and u['active']]
                    if not raw_unit and barcode_units:
                        if len(barcode_units) != 1:
                            raise ValueError('확장 바코드 단위를 유일하게 찾지 못했습니다.')
                        unit_id = barcode_units[0]['id']
                        if columns['unit_price'] is None:
                            price = public_input(barcode_units[0]['purchase_price'])
                    if raw_unit and raw_unit not in {product['base_unit'], product['base_unit']+'(100g당)'} and not gram:
                        unit_matches = [u for u in catalog['units'] if u['product_id'] == product['id'] and u['active'] and u['name'].replace(' ', '') == raw_unit]
                        if len(unit_matches) != 1:
                            raise ValueError('단위가 등록정보와 다릅니다. 확장단위를 먼저 등록하세요.')
                        unit_id = unit_matches[0]['id']
                    basis = 100 if gram else 1 if unit_id else product.get('price_basis', 1)
                    total = round_amount(quantity * price / basis, catalog['rounding_mode'])
                    if cell('total') and public_input(cell('total').replace(',', '')) != total:
                        raise ValueError('수량×단가와 파일 금액이 다릅니다. 단위·100g당 가격·반올림을 확인하세요.')
                    if cell('supplier') and not legacy:
                        matched = suppliers(cell('supplier'))
                        if len(matched) != 1 or supplier_id and supplier_id != matched[0]['id']:
                            raise ValueError('공급사가 없거나 한 파일에 여러 공급사가 있습니다.')
                        supplier_id = matched[0]['id']
                    entry['lines'].append(dict(product_id=product['id'], unit_id=unit_id,
                        gram_input=gram, qty=str(quantity), unit_price=str(price),
                        _edit_token=product['_edit_token'],
                        _unit_token=next((u['_import_token'] for u in catalog['units'] if u['id']==unit_id), None),
                        name=product['name'], total=str(total), source_row=index))
                except (ValueError, InvalidOperation) as exc:
                    raise ValueError(f'{index}행 {name}: {exc}') from exc
            if not entry['lines']:
                raise ValueError('불러올 상품이 없습니다.')
            supplier_id = supplier_id or default_supplier
            supplier = next((p for p in catalog['suppliers'] if p['id'] == supplier_id and p['active']), None)
            if not supplier:
                raise ValueError('공급사 없는 파일은 상단 기본 공급사를 선택 후 다시 불러오세요.')
            entry.update(partner_id=supplier_id, supplier_name=supplier['name'], date=date,
                         total=str(sum(Decimal(line['total']) for line in entry['lines'])),
                         price_source='단가 없는 파일 · 현재 상품 등록 매입가 사용 (과거 거래 단가 아님)' if columns['unit_price'] is None else '파일 단가 사용')
        except Exception as exc:
            entry['error'] = str(exc)
        result.append(entry)
    return result


class PurchaseImportMixin:
    def purchase_import_catalog(self):
        self.require_menu('purchases')
        from .shared_protocol import fingerprint
        units = [dict(u) for u in self.db.execute('SELECT * FROM product_units')]
        for unit in units:
            unit['_import_token'] = fingerprint(unit)
        return dict(products=self.products(), suppliers=[dict(p) for p in self.db.execute("SELECT id,name,business_no,active FROM partners WHERE kind='supplier'")],
                    units=units,
                    rounding_mode=self._settings_values().get('rounding_mode', 'decimal'))

    def import_purchase_drafts(self, files):
        if not isinstance(files, (list, tuple)) or not 1 <= len(files) <= 50:
            raise ValueError('한 번에 1~50개의 매입 파일을 선택하세요.')
        with self._tx():
            self._require_capability('purchases', 'create')
            self.db.execute('CREATE TABLE IF NOT EXISTS purchase_imports (source_hash TEXT PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE)')
            created, existing = [], []
            for file in files:
                digest = file.get('source_hash', '')
                if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
                    raise ValueError('분석한 파일을 다시 선택하세요.')
                prior = self.db.execute('SELECT document_id FROM purchase_imports WHERE source_hash=?', (digest,)).fetchone()
                if prior:
                    existing.append(prior[0]); continue
                if file.get('error') or not file.get('lines'):
                    raise ValueError('오류가 있거나 품목이 없는 파일은 등록할 수 없습니다.')
                for line in file['lines']:
                    if not line.get('_edit_token'):
                        raise ValueError('상품 검토 정보를 다시 불러오세요.')
                    self._check_edit_snapshot('products', line['product_id'], {'_expected_token': line['_edit_token']})
                    if line.get('unit_id'):
                        from .shared_protocol import fingerprint
                        unit = self.db.execute('SELECT * FROM product_units WHERE id=?', (line['unit_id'],)).fetchone()
                        if not unit or line.get('_unit_token') != fingerprint(dict(unit)):
                            raise ValueError('검토 이후 확장단위가 변경되었습니다. 파일을 다시 불러오세요.')
                prepared = self._prepare_trade(dict(kind='purchase', date=file['date'], partner_id=file['partner_id'],
                    paid=0, points_used=0, lines=file['lines'], memo=('엑셀 불러오기: '+file.get('file', '')[:150]+' / '+file.get('price_source', '파일 단가 사용'))[:500]))
                if money(file.get('total', '')) != prepared['total']:
                    raise ValueError('검토 이후 계산 결과가 달라졌습니다. 파일을 다시 불러오세요.')
                identifier = self._write_trade(prepared, 'draft')
                self.db.execute('INSERT INTO purchase_imports VALUES(?,?)', (digest, identifier))
                self._audit('import_purchase', 'document', identifier, {'source_hash': digest, 'lines': len(prepared['lines'])})
                created.append(identifier)
        return dict(created=created, existing=existing)
