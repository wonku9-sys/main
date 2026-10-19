"""Operational offline PDF menus, reports and printable non-posting papers."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QTableWidget, QVBoxLayout, QAbstractItemView, QMenu

from .widgets import Page, DataGrid, FormDialog, ScanField, action, date_field, won
from .offline_menus import REPORT_VIEWS, SALES_VIEWS, BASIC_VIEWS, MEMBER_VIEWS, FORM_VIEWS
from .common import qtext
from .currency import public_input, round_amount
from .navigation import mark_saved, confirm_dialog_exit
from .permissions import can_action


def iso(field):
    return field.date().toString("yyyy-MM-dd")


class OfflineReportPage(Page):
    def __init__(self, window, key):
        self.menu_key = key
        title, self.period, self.group, _ = {**REPORT_VIEWS, **SALES_VIEWS}[key]
        super().__init__(window, title, "저장된 확정 전표를 즉시 집계합니다. 반품 차감 · 현재 상품 분류 · 부가세 포함가 참고 계산입니다.")
        row = QHBoxLayout()
        self.start, self.end = date_field(date.today().replace(day=1)), date_field()
        if key == "sales_realtime":
            self.start.setDate(self.end.date())
        self.supplier, self.category, self.search = QComboBox(), QComboBox(), QLineEdit()
        self.search.setPlaceholderText("상품코드 · 바코드 · 상품명 · 규격")
        for control in (self.start, QLabel("~"), self.end, self.supplier, self.category, self.search):
            row.addWidget(control)
        row.addWidget(action("조회", self.refresh, primary=True))
        self.body.addLayout(row)
        self.grid = self.table(["일자 / 월", "구분", "단위", "순매입량", "순판매량", "순매입액", "순판매액", "판매원가", "매출총이익", "과세매출", "면세매출", "부가세(참고)", "수수료", "차인지급 기준액"])
        self.total = QLabel()
        self.total.setWordWrap(True)
        self.body.addWidget(self.total)
        if key in SALES_VIEWS:
            self.comparison=DataGrid(['비교 기준','시작일','종료일','순판매액','매출총이익','선택 기간과 차이','증감률'])
            self.comparison.setMaximumHeight(190);self.body.addWidget(self.comparison)
            note=QLabel('비교는 날짜 전체 기준입니다. 오늘의 진행 중 매출과 과거 하루 전체 매출을 비교하며, 전월 말일은 해당 월 마지막 날짜로 보정합니다. 다른 점포·온라인 매출은 포함하지 않습니다.');note.setWordWrap(True);self.body.addWidget(note)
        self.timer = QTimer(self)
        self.timer.setInterval(30_000)
        self.timer.timeout.connect(self.auto_refresh)
        if key == "sales_realtime":
            self.refresh_interval=QComboBox()
            for label,value in [('자동갱신 30초',30000),('자동갱신 1분',60000),('자동갱신 2분',120000),('자동갱신 5분',300000),('자동갱신 끄기',0)]:self.refresh_interval.addItem(label,value)
            row.addWidget(self.refresh_interval);self.refresh_interval.currentIndexChanged.connect(self.interval_changed)
            self.timer.start()

    def interval_changed(self):
        interval=self.refresh_interval.currentData();self.timer.stop()
        if interval:self.timer.start(interval)

    def auto_refresh(self):
        if self.isVisible() and QApplication.activeModalWidget() is None:
            try:
                self.refresh()
            except (ValueError, PermissionError) as exc:
                self.grid.fill([])
                self.timer.stop()
                self.fail(exc)

    def refresh(self):
        options = self.store.offline_report_filters(self.menu_key)
        for combo, rows, caption in ((self.supplier,options["suppliers"],"전체 공급사"), (self.category,options["categories"],"전체 분류")):
            old = combo.currentData()
            combo.clear(); combo.addItem(caption,None)
            for label, value in rows:
                combo.addItem(label,value)
            combo.setCurrentIndex(max(0,combo.findData(old)))
        report = self.store.offline_report(self.menu_key,iso(self.start),iso(self.end),self.supplier.currentData(),self.category.currentData() or "",self.search.text())
        rows = report["rows"]
        self.grid.fill([[r["period"],r["label"],r["unit"],Decimal(r["purchase_qty"]),Decimal(r["sale_qty"]),*[r[k] for k in ("purchase_total","sale_total","cost","profit","taxable_sale_total","exempt_sale_total","vat","commission_fee","payable")]] for r in rows],rows)
        totals = report["totals"]
        self.total.setText(f"순매입 {won(totals['purchase_total'])}원 · 순판매 {won(totals['sale_total'])}원 · 매출총이익 {won(totals['profit'])}원\n{report['basis']} · 수수료 차인지급액은 은행 이체나 결제 완료 금액이 아닙니다.")
        if self.menu_key in SALES_VIEWS:
            comparisons=self.store.sales_period_comparison(self.menu_key,iso(self.start),iso(self.end),self.supplier.currentData(),self.category.currentData() or '',self.search.text())
            self.comparison.fill([[r['name'],r['start'],r['end'],r['sale_total'],r['profit'],r['difference'],str(r['percent_change'])+'%' if r['percent_change'] is not None else '비교액 0원'] for r in comparisons],comparisons)


class SalesHistoryPage(Page):
    def __init__(self,window,status):
        self.menu_key='sales_held' if status=='draft' else 'sales_cancelled';self.status=status
        super().__init__(window,'보류내역' if status=='draft' else '취소내역','PDF 판매관리 이력 메뉴 · 보류는 재고·대금에 반영되지 않습니다. 취소된 전표는 삭제하지 않고 이력으로 보관합니다.')
        row=QHBoxLayout();self.start,self.end=date_field(date.today().replace(day=1)),date_field();self.search=QLineEdit();self.search.setPlaceholderText('전표번호 · 거래처 · 메모')
        for c in (self.start,QLabel('~'),self.end,self.search):row.addWidget(c)
        row.addWidget(action('조회',self.refresh));self.body.addLayout(row)
        self.grid=self.table(['날짜','전표번호','판매처','작성자','금액','메모']);self.grid.cellDoubleClicked.connect(lambda *_:self.detail())
        self.body.addWidget(action('선택 전표 상세',self.detail));self.total=QLabel();self.body.addWidget(self.total)
    def refresh(self):
        rows=self.store.sales_history(self.status,iso(self.start),iso(self.end),self.search.text());self.grid.fill([[r['date'],r['number'],r['partner_name'],r['user_name'],r['total'],r['memo']] for r in rows],rows)
        self.total.setText(f"{len(rows)}건 · {won(sum(r['total'] for r in rows))}원 · 확정 매출 합계에는 포함하지 않습니다.")
    def detail(self):
        row=self.grid.selected()
        if not row:return
        try:
            document=self.store.document(row['id']);d=QDialog(self);d.resize(950,580);d.setWindowTitle('판매 전표 이력 · 읽기 전용');layout=QVBoxLayout(d)
            layout.addWidget(QLabel(document['number']+' · '+document['date']+' · '+document['partner_name']))
            grid=DataGrid(['상품명','입력수량','단위','단가','금액']);layout.addWidget(grid,1)
            grid.fill([[r['product_name'],r['input_qty'],r['unit_name'],r['unit_price'],r['total']] for r in document['lines']])
            layout.addWidget(action('닫기',d.reject));d.exec();d.deleteLater()
        except (ValueError,PermissionError) as exc:self.fail(exc)


class BasicRecordsPage(Page):
    def __init__(self, window, key):
        self.menu_key = key
        super().__init__(window,BASIC_VIEWS[key],"상품 정보와 변경 이력을 조회합니다. 사용 이력은 삭제하지 않습니다.")
        row = QHBoxLayout()
        self.search = ScanField(); self.search.setPlaceholderText("코드 · 상품명 · 바코드 / 로그 내용 검색")
        self.search.scanned.connect(lambda _: self.refresh())
        row.addWidget(self.search,1); row.addWidget(action("조회",self.refresh))
        if key not in {"product_changes","user_access"}:
            row.addWidget(action("상품 등록정보",self.edit))
        self.body.addLayout(row)
        self.headers = ["시각","담당자","작업","대상 코드(ID)","변경 내용 (이전 값 → 새 값)"] if key in {"product_changes","user_access"} else ["상품코드","상품명","확장단위","바코드","환산수량","매입단가","판매단가","상태"] if key == "product_units" else ["상품코드","상품명","규격","단위","매입단가","판매단가","상태","원산지"]
        self.grid = self.table(self.headers)
        self.grid.cellDoubleClicked.connect(lambda *_:self.edit())
        if key == "product_units":
            self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.grid.customContextMenuRequested.connect(self.context_menu)

    def refresh(self):
        records = self.store.basic_records(self.menu_key,self.search.text())
        if self.menu_key in {"product_changes","user_access"}:
            from .catalog_ui import ProductDialog
            rows = [[r["at"],r["user_name"],r["action"],r["entity_id"],ProductDialog._audit_text(r["detail"])] for r in records]
        elif self.menu_key == "product_units":
            rows = [[r["product_code"],r["product_name"],r["name"],r["barcode"],Decimal(qtext(r["factor"])),r["purchase_price"],r["sale_price"],"유효" if r["active"] else "무효"] for r in records]
        else:
            rows = [[r["code"],r["name"],r["specification"],f"100{r['base_unit']}당" if r["price_basis"]==100 else r["base_unit"],r["purchase_price"],r["sale_price"],"유효" if r["active"] else "무효",r["origin"]] for r in records]
        self.grid.fill(rows,records)

    def edit(self):
        if self.menu_key in {"product_changes","user_access"}:
            selected = self.grid.selected()
            if selected:
                QMessageBox.information(self,"변경 내용",str(selected["detail"]))
            return
        selected = self.grid.selected()
        if not selected:
            return
        from .catalog_ui import ProductDialog
        try:
            self.store.require_menu("products")
            record = next(r for r in self.store.products() if r["id"] == selected.get("product_id",selected["id"]))
            dialog = ProductDialog(self.store,record,self)
            if self.menu_key == "product_units":
                dialog.tabs.setCurrentIndex(0)
            dialog.exec(); self.refresh()
        except (ValueError,PermissionError,StopIteration) as exc:
            self.fail(exc)

    def make_context_menu(self):
        menu = QMenu(self)
        selected = self.grid.selected()
        def item(label,callback,enabled=True):
            entry = menu.addAction(label)
            entry.setEnabled(bool(selected) and enabled)
            entry.triggered.connect(lambda checked=False:callback())
        item("상품 등록정보",self.edit)
        item("확장단위 추가 / 수정",self.edit_unit,can_action(self.store.actor,"products","edit"))
        item("확장단위 판매가 설정",self.unit_price,can_action(self.store.actor,"products","edit"))
        menu.addSeparator()
        item("라벨 출력",self.unit_labels)
        item("확장 바코드 복사",self.copy_unit_barcode)
        columns = menu.addMenu("열 선택")
        for column in range(self.grid.columnCount()):
            entry = columns.addAction(self.grid.horizontalHeaderItem(column).text()); entry.setCheckable(True)
            entry.setChecked(not self.grid.isColumnHidden(column))
            entry.toggled.connect(lambda shown,c=column:self.grid.setColumnHidden(c,not shown))
        return menu

    def context_menu(self,position):
        target = self.grid.indexAt(position)
        if target.isValid(): self.grid.selectRow(target.row())
        self.make_context_menu().exec(self.grid.viewport().mapToGlobal(position))

    def edit_unit(self):
        selected = self.grid.selected()
        if not selected: return
        from .catalog_ui import ProductDialog
        try:
            self.store.require_menu("products")
            record = next(r for r in self.store.products() if r["id"]==selected["product_id"])
            dialog = ProductDialog(self.store,record,self)
            unit = next(r for r in self.store.units(selected["product_id"]) if r["id"]==selected["id"])
            dialog.tabs.setCurrentIndex(dialog.tabs.count()-1)
            dialog._unit_editor(unit)
            dialog.deleteLater(); self.refresh()
        except (ValueError,PermissionError) as exc: self.fail(exc)

    def unit_price(self):
        selected = self.grid.selected()
        if not selected: return
        from .catalog_ui import EntryDialog
        dialog = EntryDialog("확장단위 판매가",self)
        value = dialog.field("price","확장단위 1개당 판매가 (원)",selected["sale_price"])
        dialog.finish(lambda:self.store.save_unit({"sale_price":value.text()},selected["id"]))
        if dialog.exec(): self.refresh()

    def copy_unit_barcode(self):
        self.store.require_menu(self.menu_key)
        selected = self.grid.selected()
        if selected: QApplication.clipboard().setText(selected["barcode"])

    def unit_labels(self):
        selected = self.grid.selected()
        if selected:
            from .labels import LabelDialog
            LabelDialog(self.store,[selected["product_id"]],self).exec()


class MemberViewPage(Page):
    COLUMNS = {
        "member_best": [("회원코드","code"),("회원명","name"),("판매 횟수","sale_count"),("순구매액","total"),("현재 포인트","points"),("첫 구매","first_purchase"),("최근 구매","last_purchase")],
        "member_points": [("일자","date"),("회원코드","code"),("회원명","name"),("구분","kind"),("증감","delta"),("등록순 잔액","point_balance"),("사유","reason")],
        "member_transactions": [("일자","date"),("전표번호","number"),("회원명","name"),("구분","kind"),("상태","status"),("거래액","total"),("사용 포인트","points_used"),("적립 포인트","points_earned")],
        "member_prices": [("회원코드","code"),("회원명","name"),("상품명","product_name"),("지정 판매가","price")],
        "gift_history": [("일시","created_at"),("회원코드","code"),("회원명","name"),("사은품","gift_name"),("구분","kind"),("수량","qty"),("포인트","points"),("사유","reason")],
    }
    def __init__(self,window,key):
        self.menu_key = key
        super().__init__(window,MEMBER_VIEWS[key],"회원의 로컬 거래·포인트를 조회합니다. 취소·초안은 상태를 구분하고, 구매 순위는 확정 순구매액 기준입니다.")
        row = QHBoxLayout()
        self.start,self.end = date_field(date.today().replace(day=1)),date_field()
        self.member,self.search = QComboBox(),QLineEdit()
        self.search.setPlaceholderText("회원명 · 회원코드")
        for control in (self.start,QLabel("~"),self.end,self.member,self.search): row.addWidget(control)
        row.addWidget(action("조회",self.refresh,primary=True))
        if key == "member_points": row.addWidget(action("포인트 조정",self.adjust))
        if key == "member_prices": row.addWidget(action("지정가 등록·수정",self.edit_price))
        self.body.addLayout(row)
        self.columns = self.COLUMNS[key]
        self.grid = self.table([label for label,_ in self.columns])
        self.grid.cellDoubleClicked.connect(lambda *_:self.detail())

    def refresh(self):
        current = self.member.currentData()
        self.member.clear(); self.member.addItem("전체 회원",None)
        for r in self.store.trade_members(): self.member.addItem(f"{r['code']} · {r['name']}",r["id"])
        self.member.setCurrentIndex(max(0,self.member.findData(current)))
        rows = self.store.member_view(self.menu_key,iso(self.start),iso(self.end),self.member.currentData(),self.search.text())
        if self.menu_key == "member_best":
            rows = [r for r in rows if (not self.member.currentData() or r["id"]==self.member.currentData()) and (self.search.text() in r["name"] or self.search.text() in r["code"])]
        self.grid.fill([[r.get(key,"") for _,key in self.columns] for r in rows],rows)

    def adjust(self):
        selected = self.member.currentData()
        record = self.grid.selected()
        if not selected and record: selected = record["member_id"]
        if not selected:
            QMessageBox.information(self,"회원 선택","포인트를 조정할 회원을 선택하세요."); return
        from .loyalty_ui import change
        dialog = FormDialog("포인트 조정",self)
        delta = dialog.field("delta","증감 포인트 (+적립 / -차감)")
        reason = dialog.field("reason","사유 *")
        dialog.finish(lambda:change(dialog,lambda:self.store.adjust_points(selected,delta.text(),reason.text())))
        if dialog.exec(): self.refresh()

    def edit_price(self):
        if self.window.open_page("members"):
            page = self.window.current_page
            if self.member.currentData():
                for row in range(page.grid.rowCount()):
                    if page.grid.item(row,0).data(Qt.ItemDataRole.UserRole)["id"] == self.member.currentData(): page.grid.selectRow(row); break
            page.tabs.setCurrentIndex(2)

    def detail(self):
        row = self.grid.selected()
        if not row: return
        try:
            if self.menu_key == "member_transactions":
                from .workflow_ui import TradeDialog
                TradeDialog(self.window,record=self.store.document(row["id"])).exec()
            else:
                from .loyalty_ui import MemberDialog
                identifier = row["id"] if self.menu_key == "member_best" else row["member_id"]
                member = next(r for r in self.store.members() if r["id"]==identifier)
                if MemberDialog(self.store,member,self).exec(): self.refresh()
        except (ValueError,PermissionError) as exc: self.fail(exc)


class SalesFormDialog(FormDialog):
    def __init__(self,window,key,record=None,source_ids=None,parent=None):
        self.window,self.store,self.menu_key = window,window.store,key
        self.kind = FORM_VIEWS[key][1]
        self.record,self.source_ids = record,source_ids or []
        self.readonly = not can_action(self.store.actor,key,"edit" if record else "create")
        super().__init__(FORM_VIEWS[key][0],parent or window)
        self.resize(1040,740)
        self.date = date_field((record or {}).get("date"))
        from .date_input import DateInput
        self.valid=DateInput((record or {}).get('valid_until',''))
        self.fields['valid_until']=self.valid;self.form.addRow('유효기간 · 직접 입력 / 달력 선택 (선택)',self.valid)
        self.memo = self.field("memo","메모",(record or {}).get("memo",""))
        self.form.addRow("작성일",self.date)
        self.partner = QComboBox()
        if self.kind == "quotation":
            for r in self.store.trade_partners("customer"): self.partner.addItem(f"{r['code']} · {r['name']}",r["id"])
        elif record:
            self.partner.addItem(record["customer"]["name"],record["partner_id"])
        self.form.addRow("판매처",self.partner)
        self.manual = self.kind == "quotation" and not self.source_ids and not (record or {}).get("source_ids")
        self.rows = []
        self.rounding_mode = (record or {}).get("rounding_mode",self.store.calculation_policy()["rounding_mode"])
        self.body.addWidget(QLabel("견적서·거래명세서·계산서 참고자료는 재고·매출·결제·포인트를 변경하지 않습니다. 세금 신고·전자세금계산서 발행 기능이 아닙니다."))
        self.table = QTableWidget(0,6)
        self.table.setHorizontalHeaderLabels(["상품","단위","수량","단가","금액","삭제"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.body.addWidget(self.table,1)
        self.products = {r["id"]:r for r in self.store.trade_products()} if self.manual else {}
        self.total = QLabel()
        self.body.addWidget(self.total)
        if self.manual:
            tools = QHBoxLayout()
            self.scan = ScanField(); self.scan.setPlaceholderText("바코드 스캔 후 Enter")
            self.scan.scanned.connect(self.scan_product)
            tools.addWidget(self.scan,1); tools.addWidget(action("품목 추가",self.add_line))
            self.body.addLayout(tools)
            if record:
                self.partner.setCurrentIndex(max(0,self.partner.findData(record["partner_id"])))
                for line in record["lines"]: self.add_line(line["product_id"],line)
            else: self.add_line()
        else:
            self.partner.setEnabled(False)
            if record:
                grid = self.paper_grid(record)
                self.body.replaceWidget(self.table,grid); self.table.hide()
                self.total.setText(f"{record['number']} · 合計 {won(record['total'])}원".replace("合計","합계"))
            else:
                self.body.addWidget(QLabel(f"선택한 판매전표 {len(self.source_ids)}개 · 저장 후 원판매전표의 상품·금액·판매처가 고정됩니다."))
                self.table.hide()
        self.finish(self.save)
        self.recalculate()
        if self.readonly:
            for control in self.findChildren(QLineEdit): control.setReadOnly(True)
            self.partner.setEnabled(False); self.date.setEnabled(False)
            self.buttons.button(self.buttons.StandardButton.Save).setEnabled(False)

    def reject(self):
        if confirm_dialog_exit(self): super().reject()

    def add_line(self,identifier=None,saved=None):
        if self.readonly: return
        # QPushButton's checked bool is not a product identifier.
        if isinstance(identifier,bool): identifier=None
        row = dict(product=QComboBox(),unit=QComboBox(),qty=QLineEdit("1"),price=QLineEdit("0.00"),total=QLabel("0.00"))
        for p in self.products.values(): row["product"].addItem(f"{p['code']} · {p['name']}",p["id"])
        if identifier: row["product"].setCurrentIndex(max(0,row["product"].findData(identifier)))
        self.rows.append(row)
        index = self.table.rowCount(); self.table.insertRow(index)
        for col,key in enumerate(("product","unit","qty","price","total")): self.table.setCellWidget(index,col,row[key])
        self.table.setCellWidget(index,5,action("삭제",lambda:self.remove(row)))
        row["product"].currentIndexChanged.connect(lambda _:self.product_changed(row))
        row["unit"].currentIndexChanged.connect(lambda _:self.unit_changed(row))
        row["qty"].textChanged.connect(self.recalculate); row["price"].textChanged.connect(self.recalculate)
        self.product_changed(row)
        if saved:
            row["unit"].setCurrentIndex(max(0,row["unit"].findData(saved.get("unit_id"))))
            row["qty"].setText(saved["qty"]); row["price"].setText(str(saved["unit_price"]))

    def product_changed(self,row):
        row["unit"].blockSignals(True); row["unit"].clear()
        product = self.products.get(row["product"].currentData())
        if product:
            row["unit"].addItem("100g당" if product["price_basis"]==100 else product["base_unit"],None)
            row["units"] = {u["id"]:u for u in product.get("units",[]) if u["active"]}
            for unit in row["units"].values(): row["unit"].addItem(unit["name"],unit["id"])
        row["unit"].blockSignals(False); self.unit_changed(row)

    def unit_changed(self,row):
        identifier = row["product"].currentData()
        if not identifier: return
        quote = self.store.quote(identifier,iso(self.date),row["unit"].currentData())
        row["price"].setText(str(quote["price"])); self.recalculate()

    def remove(self,row):
        index = self.rows.index(row); self.rows.remove(row); self.table.removeRow(index); self.recalculate()

    def scan_product(self,barcode):
        try:
            found = self.store.lookup_barcode(barcode)
            if not found: raise ValueError("상품장에 먼저 상품을 등록하세요.")
            self.add_line(found["product"]["id"])
            row = self.rows[-1]
            row["unit"].setCurrentIndex(max(0,row["unit"].findData((found.get("unit") or {}).get("id"))))
            row["qty"].setFocus(); row["qty"].selectAll()
        except (ValueError,PermissionError) as exc: self.error(exc)

    def recalculate(self,*_):
        if not getattr(self,"manual",False): return
        total = Decimal(0)
        try:
            for row in self.rows:
                product = self.products.get(row["product"].currentData())
                if not product: continue
                from .common import qty
                quantity = Decimal(qty(row["qty"].text(),allow_zero=True))/1000
                basis = 1 if row["unit"].currentData() else product["price_basis"]
                value = round_amount(quantity*public_input(row["price"].text())/basis,self.rounding_mode)
                row["total"].setText(won(value)); total += value
            self.total.setText(f"합계 {won(total)}원 · {'원 단위 반올림' if self.rounding_mode=='won' else '소수점 두 자리 보존'}")
        except ValueError: self.total.setText("수량과 단가를 확인하세요.")

    def save(self):
        if self.readonly: return
        try:
            data = {"date":iso(self.date),"valid_until":self.valid.text(),"memo":self.memo.text(),"source_ids":self.source_ids,"partner_id":self.partner.currentData(),"rounding_mode":self.rounding_mode,"lines":[{"product_id":r["product"].currentData(),"unit_id":r["unit"].currentData(),"qty":r["qty"].text(),"unit_price":r["price"].text()} for r in self.rows]}
            self.saved_id = self.store.save_sales_form(self.kind,data,(self.record or {}).get("id"))
            mark_saved(self); self.accept()
        except (ValueError,PermissionError) as exc: self.error(exc)

    @staticmethod
    def paper_grid(record):
        grid = DataGrid(["상품명","단위","수량","가격 기준","단가","금액","과면세"])
        grid.fill([[r["product_name"],r["unit_name"],Decimal(r["qty"]),f"{r.get('price_basis',1)} {r['unit_name']}당",r["unit_price"],r["total"],"과세" if r["tax_mode"]=="taxable" else "면세"] for r in record["lines"]])
        return grid


class SalesFormsPage(Page):
    def __init__(self,window,key):
        self.menu_key,self.kind = key,FORM_VIEWS[key][1]
        super().__init__(window,FORM_VIEWS[key][0],"저장·인쇄·PDF·엑셀 출력용 문서입니다. 작성해도 재고·전표·결제는 바뀌지 않습니다.")
        self.actions.addWidget(action("새 문서",self.add,primary=True))
        self.actions.addWidget(action("등록정보",self.edit))
        self.actions.addWidget(action("삭제",self.delete,danger=True))
        row = QHBoxLayout()
        self.start,self.end,self.search = date_field(date.today().replace(day=1)),date_field(),QLineEdit()
        self.search.setPlaceholderText("문서번호 · 판매처 · 메모")
        for control in (self.start,QLabel("~"),self.end,self.search): row.addWidget(control)
        row.addWidget(action("조회",self.refresh)); row.addWidget(action("문서 인쇄·PDF",self.print_paper)); row.addWidget(action("문서 엑셀",self.export_paper))
        self.body.addLayout(row)
        self.grid = self.table(["작성일","문서번호","판매처","합계","유효기한","메모"])
        self.grid.cellDoubleClicked.connect(lambda *_:self.edit())

    def refresh(self):
        rows = self.store.sales_forms(self.kind,iso(self.start),iso(self.end),self.search.text())
        self.grid.fill([[r["date"],r["number"],r["partner_name"],r["total"],r["valid_until"],r["memo"]] for r in rows],rows)

    def add(self):
        if not can_action(self.store.actor,self.menu_key,"create"):
            self.fail("문서 등록 권한이 없습니다."); return
        source_ids = []
        if self.kind != "quotation":
            picker = QDialog(self); picker.setWindowTitle("원판매전표 선택 · 같은 판매처·회원끼리 선택"); picker.resize(1000,650)
            layout = QVBoxLayout(picker)
            grid = DataGrid(["일자","전표번호","판매처","회원","합계"])
            grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            rows = self.store.form_sources(self.kind=="tax_reference")
            grid.fill([[r["date"],r["number"],r["partner_name"],r["member_name"] or "비회원",r["total"]] for r in rows],rows)
            layout.addWidget(QLabel("Ctrl/Shift로 여러 전표를 선택하세요. 이 작업은 새로운 매출을 등록하지 않습니다.")); layout.addWidget(grid,1)
            layout.addWidget(action("선택 적용",picker.accept)); layout.addWidget(action("닫기",picker.reject))
            if not picker.exec(): return
            source_ids = [grid.item(index.row(),0).data(Qt.ItemDataRole.UserRole)["id"] for index in grid.selectionModel().selectedRows()]
            if not source_ids:
                self.fail("원판매전표를 선택하세요."); return
        if SalesFormDialog(self.window,self.menu_key,source_ids=source_ids,parent=self).exec(): self.refresh()

    def edit(self):
        row = self.grid.selected()
        if row and SalesFormDialog(self.window,self.menu_key,self.store.sales_form(row["id"]),parent=self).exec(): self.refresh()

    def delete(self):
        row = self.grid.selected()
        if row and QMessageBox.question(self,"문서 삭제","선택한 문서를 삭제할까요? 실제 판매전표는 삭제되지 않습니다.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            try: self.store.delete_sales_form(row["id"]); self.refresh()
            except (ValueError,PermissionError) as exc: self.fail(exc)

    def output_data(self):
        row = self.grid.selected()
        if not row: return None
        record = self.store.sales_form(row["id"])
        seller,customer,member = record["seller"],record["customer"],record["member"]
        taxable = sum(r["total"] for r in record["lines"] if r["tax_mode"]=="taxable")
        vat = round_amount(taxable/11)
        warning = "원판매전표 취소됨 · 이 문서는 유효 거래내역으로 사용하지 마세요.\n" if any(r["status"]!="posted" for r in record["source_states"]) else ""
        info = f"{warning}{record['number']} · 작성일 {record['date']} · 유효기한 {record['valid_until'] or '미지정'}\n공급자: {seller['store_name']} / 사업자번호 {seller.get('business_no','')} / {seller.get('phone','')} / {seller.get('address','')}\n공급받는 자: {customer['name']} / {member.get('name','')} / 사업자번호 {member.get('business_no') or customer.get('business_no','')}\n합계 {won(record['total'])}원 · 과세 공급가 {won(taxable-vat)}원 · 부가세(참고) {won(vat)}원 · 면세 {won(record['total']-taxable)}원\n{record['memo']}\n재고·결제 미반영 문서 / 전자세금계산서·세무 신고용 법정 서식이 아닙니다."
        return record,info

    def print_paper(self):
        try:
            data = self.output_data()
            if data:
                grid = SalesFormDialog.paper_grid(data[0]); grid.print_pages(self,self.title,data[1]); grid.deleteLater()
        except (ValueError,PermissionError) as exc: self.fail(exc)

    def export_paper(self):
        try:
            data = self.output_data()
            if data:
                from .widgets import export_rows
                record,info = data
                rows = [[record["number"],record["date"],record["customer"]["name"],r["product_name"],r["unit_name"],Decimal(r["qty"]),r["price_basis"],r["unit_price"],r["total"],info] for r in record["lines"]]
                export_rows(self,self.title,["문서번호","작성일","판매처","상품","단위","수량","가격 기준","단가","금액","문서 정보"],rows)
        except (ValueError,PermissionError) as exc: self.fail(exc)
