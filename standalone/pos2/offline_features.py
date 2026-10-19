"""Local report views and non-posting commercial paper. No external services."""
from decimal import Decimal
import json
from uuid import uuid4
from datetime import datetime, date as calendar_date,timedelta

from .common import day, text, now, qtext, rounded, LIMIT
from .currency import amount
from .offline_menus import REPORT_VIEWS, SALES_VIEWS, BASIC_VIEWS, MEMBER_VIEWS, FORM_VIEWS

OFFLINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS desk_event_rules (
 event_id INTEGER PRIMARY KEY REFERENCES desk_events(id) ON DELETE CASCADE,
 calendar TEXT NOT NULL CHECK(calendar IN ('solar','lunar')),
 repeat TEXT NOT NULL CHECK(repeat IN ('once','yearly')),
 event_kind TEXT NOT NULL,base_year INTEGER NOT NULL,month INTEGER NOT NULL,day INTEGER NOT NULL,
 leap INTEGER NOT NULL CHECK(leap IN (0,1)),lead_days INTEGER NOT NULL CHECK(lead_days BETWEEN 0 AND 365),
 leap_fallback INTEGER NOT NULL CHECK(leap_fallback IN (0,1))
);
CREATE TABLE IF NOT EXISTS desk_event_receipts (
 event_id INTEGER NOT NULL REFERENCES desk_events(id) ON DELETE CASCADE,
 occurrence TEXT NOT NULL,notified_at TEXT NOT NULL,PRIMARY KEY(event_id,occurrence)
);
CREATE TABLE IF NOT EXISTS desk_events (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 date TEXT NOT NULL, time TEXT NOT NULL DEFAULT '09:00', title TEXT NOT NULL,
 notes TEXT NOT NULL DEFAULT '', alarm INTEGER NOT NULL DEFAULT 0 CHECK(alarm IN (0,1)),
 done INTEGER NOT NULL DEFAULT 0 CHECK(done IN (0,1)),
 notified_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS member_profiles (
 member_id INTEGER PRIMARY KEY REFERENCES members(id) ON DELETE CASCADE,
 mobile TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '',
 member_type TEXT NOT NULL DEFAULT '일반고객', business_no TEXT NOT NULL DEFAULT '',
 company TEXT NOT NULL DEFAULT '', representative TEXT NOT NULL DEFAULT '',
 group_name TEXT NOT NULL DEFAULT '', anniversary TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sales_forms (
 id INTEGER PRIMARY KEY, number TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL CHECK(kind IN ('quotation','statement','tax_reference')),
 date TEXT NOT NULL, valid_until TEXT NOT NULL DEFAULT '',
 partner_id INTEGER NOT NULL REFERENCES partners(id) ON DELETE RESTRICT,
 member_id INTEGER REFERENCES members(id) ON DELETE RESTRICT,
 total INTEGER NOT NULL CHECK(total BETWEEN 0 AND 9000000000000),
 rounding_mode TEXT NOT NULL CHECK(rounding_mode IN ('decimal','won')),
 content TEXT NOT NULL, memo TEXT NOT NULL DEFAULT '',
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


class OfflineFeaturesMixin:
    def desk_events(self,start,end):
        self.require_menu("home")
        start,end = day(start),day(end)
        if start>end: raise ValueError("조회 기간을 확인하세요.")
        if (calendar_date.fromisoformat(end)-calendar_date.fromisoformat(start)).days>3660:raise ValueError('조회 기간은 10년 이내로 지정하세요.')
        from .recurrence import event_rows
        return event_rows(self,calendar_date.fromisoformat(start),calendar_date.fromisoformat(end))

    def save_desk_event(self,data,identifier=None):
        with self._tx():
            self.require_menu("home")
            old = self.db.execute("SELECT * FROM desk_events WHERE id=? AND user_id=?",(identifier,self.actor["id"])).fetchone() if identifier else None
            if identifier and not old: raise ValueError("일정을 찾을 수 없습니다.")
            rule=None
            if 'calendar' in data:
                from .recurrence import validate_rule
                rule,origin=validate_rule(data);date=origin.isoformat()
            else:date = day(data.get("date",old["date"] if old else None))
            time = text(data.get("time",old["time"] if old else "09:00"),"시각",True)
            try:
                if datetime.strptime(time,"%H:%M").strftime("%H:%M")!=time: raise ValueError()
            except ValueError: raise ValueError("알림 시각은 HH:MM으로 입력하세요.") from None
            title = text(data.get("title",old["title"] if old else ""),"일정 제목",True,200)
            notes = text(data.get("notes",old["notes"] if old else ""),"메모",maximum=10000)
            alarm = int(bool(data.get("alarm",old["alarm"] if old else False)))
            done = int(bool(data.get("done",old["done"] if old else False)))
            stamp = now()
            notified = old["notified_at"] if old and (date,time,alarm)==(old["date"],old["time"],old["alarm"]) else ""
            if old:
                self.db.execute("UPDATE desk_events SET date=?,time=?,title=?,notes=?,alarm=?,done=?,notified_at=?,updated_at=? WHERE id=?",(date,time,title,notes,alarm,done,notified,stamp,identifier))
            else:
                identifier = self.db.execute("INSERT INTO desk_events(user_id,date,time,title,notes,alarm,done,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(self.actor["id"],date,time,title,notes,alarm,done,stamp,stamp)).lastrowid
            if rule:
                columns=('calendar','repeat','event_kind','base_year','month','day','leap','lead_days','leap_fallback')
                self.db.execute('INSERT INTO desk_event_rules VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET '+','.join(f'{c}=excluded.{c}' for c in columns),(identifier,*(rule[c] for c in columns)))
                self.db.execute('DELETE FROM desk_event_receipts WHERE event_id=?',(identifier,))
                self.db.execute("UPDATE desk_events SET notified_at='' WHERE id=?",(identifier,))
            self._audit("update" if old else "create","desk_event",identifier,{"date":date,"alarm":alarm,"done":done})
            return identifier

    def delete_desk_event(self,identifier):
        with self._tx():
            self.require_menu("home")
            if not self.db.execute("DELETE FROM desk_events WHERE id=? AND user_id=?",(identifier,self.actor["id"])).rowcount:
                raise ValueError("일정을 찾을 수 없습니다.")
            self._audit("delete","desk_event",identifier,{})

    def due_desk_alerts(self,at=None):
        with self._tx():
            self.require_menu("home")
            current = at or datetime.now().isoformat(timespec="minutes")
            try: current = datetime.fromisoformat(current).strftime("%Y-%m-%dT%H:%M")
            except (ValueError,TypeError): raise ValueError("알림 확인 시각을 확인하세요.") from None
            from .recurrence import event_rows
            today=calendar_date.fromisoformat(current[:10])
            legacy=[dict(r) for r in self.db.execute("SELECT e.* FROM desk_events e LEFT JOIN desk_event_rules r ON r.event_id=e.id WHERE e.user_id=? AND (r.repeat IS NULL OR r.repeat='once') AND e.alarm=1 AND e.done=0 AND e.notified_at='' AND date(e.date,'-'||COALESCE(r.lead_days,0)||' days')||'T'||e.time<=?",(self.actor['id'],current))]
            receipts={r[0]:r[1] for r in self.db.execute('SELECT event_id,MAX(occurrence) FROM desk_event_receipts GROUP BY event_id')}
            latest={}
            for item in event_rows(self,today-timedelta(days=730),today+timedelta(days=365)):
                if item.get('repeat')!='yearly' or not item['alarm'] or item['done'] or item['notified_at'] or item['date']<=receipts.get(item['id'],''):continue
                trigger=(calendar_date.fromisoformat(item['date'])-timedelta(days=item['lead_days'])).isoformat()+'T'+item['time']
                # A historical birth/wedding date must not emit decades of old alerts.
                if trigger>current or item['repeat']=='yearly' and trigger[:10]<item['created_at'][:10]:continue
                latest[item['id']]=item
            rows=sorted(legacy+list(latest.values()),key=lambda r:(r['date'],r['time'],r['id']))[:10]
            for row in rows:
                if row.get('repeat')=='yearly':self.db.execute('INSERT OR IGNORE INTO desk_event_receipts VALUES(?,?,?)',(row['id'],row['date'],current))
                else:self.db.execute("UPDATE desk_events SET notified_at=? WHERE id=?",(current,row["id"]))
            return rows

    def home_calendar(self, start, end):
        actor = self.require_menu("home")
        from .permissions import has_menu
        start,end = day(start),day(end)
        if start>end or (calendar_date.fromisoformat(end)-calendar_date.fromisoformat(start)).days>42:
            raise ValueError("달력 조회 기간을 확인하세요.")
        purchase = has_menu(actor,"purchases") or has_menu(actor,"overview")
        sales = has_menu(actor,"sales") or has_menu(actor,"overview")
        rows = {}
        for r in self.db.execute("SELECT date,kind,SUM(total) total FROM documents WHERE status='posted' AND date BETWEEN ? AND ? GROUP BY date,kind",(start,end)):
            key = "purchase_total" if r["kind"].startswith("purchase") else "sale_total"
            if (key=="purchase_total" and purchase) or (key=="sale_total" and sales):
                entry = rows.setdefault(r["date"],{"purchase_total":0,"sale_total":0})
                entry[key] += (-1 if r["kind"].endswith("return") else 1)*r["total"]
        return {"days":rows,"purchase_visible":purchase,"sale_visible":sales}

    def _form_menu(self, kind):
        for key, (_, value) in FORM_VIEWS.items():
            if value == kind:
                return key
        raise ValueError("문서 종류를 확인하세요.")

    def sales_forms(self, kind, start, end, search=""):
        self.require_menu(self._form_menu(kind))
        start, end = day(start), day(end)
        if start > end:
            raise ValueError("조회 기간을 확인하세요.")
        return [dict(r) for r in self.db.execute("SELECT f.*,p.name partner_name FROM sales_forms f JOIN partners p ON p.id=f.partner_id WHERE f.kind=? AND f.date BETWEEN ? AND ? AND (f.number LIKE ? OR p.name LIKE ? OR f.memo LIKE ?) ORDER BY f.date DESC,f.id DESC", (kind, start, end, *[f"%{text(search)}%"]*3))]

    def sales_form(self, identifier):
        row = self.db.execute("SELECT * FROM sales_forms WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise ValueError("문서를 찾을 수 없습니다.")
        self.require_menu(self._form_menu(row["kind"]))
        result = dict(row)
        result.update(json.loads(result.pop("content")))
        for line in result["lines"]:
            for key in ("unit_price", "total"):
                line[key] = int(line[key])
        result["source_states"] = [dict(r) for source in result.get("source_ids", []) for r in self.db.execute("SELECT id,number,status FROM documents WHERE id=?", (source,))]
        return result

    def form_sources(self, member_only=False):
        self.require_menu("member_tax" if member_only else "statements")
        return [dict(r) for r in self.db.execute("SELECT d.id,d.date,d.number,d.total,d.partner_id,d.member_id,p.name partner_name,m.name member_name FROM documents d JOIN partners p ON p.id=d.partner_id LEFT JOIN members m ON m.id=d.member_id WHERE d.kind='sale' AND d.status='posted'" + (" AND d.member_id IS NOT NULL" if member_only else "") + " ORDER BY d.date DESC,d.id DESC")]

    def save_sales_form(self, kind, data, identifier=None):
        menu = self._form_menu(kind)
        with self._tx():
            self._require_capability(menu, "edit" if identifier else "create")
            old = self.db.execute("SELECT * FROM sales_forms WHERE id=? AND kind=?", (identifier, kind)).fetchone() if identifier else None
            if identifier and not old:
                raise ValueError("문서를 찾을 수 없습니다.")
            date = day(data.get("date"))
            valid_until = day(data["valid_until"]) if data.get("valid_until") else ""
            if valid_until and valid_until < date:
                raise ValueError("유효기한은 작성일 이후로 지정하세요.")
            memo = text(data.get("memo", ""), "메모")
            if old and not (kind == "quotation" and data.get("lines") and not json.loads(old["content"]).get("source_ids")):
                # Keep an issued paper's items, company and price snapshots.
                content, total, mode, partner, member = old["content"], old["total"], old["rounding_mode"], old["partner_id"], old["member_id"]
            else:
                sources = list(dict.fromkeys(data.get("source_ids", [])))
                if len(sources) > 200:
                    raise ValueError("한 문서에는 전표 200개까지 선택하세요.")
                if sources:
                    lines, docs = [], []
                    for source in sources:
                        row = self._trade_row(source)
                        if row["status"] != "posted" or row["kind"] != "sale":
                            raise ValueError("확정된 판매전표만 선택하세요.")
                        docs.append(row)
                        for raw in self.db.execute("SELECT * FROM document_lines WHERE document_id=? ORDER BY id", (source,)):
                            line = dict(raw)
                            line["qty"] = qtext(line["input_qty"])
                            line["source_number"] = row["number"]
                            lines.append(line)
                    partner, member, mode = docs[0]["partner_id"], docs[0]["member_id"], docs[0]["rounding_mode"]
                    if any(d["partner_id"] != partner or d["member_id"] != member for d in docs):
                        raise ValueError("같은 판매처·회원의 전표끼리 선택하세요.")
                    if kind == "tax_reference" and not member:
                        raise ValueError("회원이 지정된 판매전표를 선택하세요.")
                    total = sum(d["total"] for d in docs)
                else:
                    if kind != "quotation":
                        raise ValueError("원판매전표를 선택하세요. 이 문서는 실제 판매내역을 기준으로 작성합니다.")
                    prepared = self._prepare_trade(dict(data, kind="sale", paid=0, points_used=0), posting=False)
                    partner, member, mode = prepared["partner_id"], prepared["member_id"], prepared["rounding_mode"]
                    lines = prepared["lines"]
                    for line in lines:
                        line["qty"] = qtext(line["input_qty"])
                    total = prepared["total"]
                if not 0 <= total <= LIMIT:
                    raise ValueError("문서 합계가 허용 범위를 초과합니다.")
                customer = dict(self.db.execute("SELECT * FROM partners WHERE id=?", (partner,)).fetchone())
                member_info = dict(self._member_row(member)) if member else {}
                if member:
                    profile = self.db.execute("SELECT * FROM member_profiles WHERE member_id=?", (member,)).fetchone()
                    if profile:
                        member_info.update(dict(profile))
                content = json.dumps({"lines": lines, "source_ids": sources, "seller": self._settings_values(), "customer": customer, "member": member_info}, ensure_ascii=False, default=str)
            stamp = now()
            if old:
                self.db.execute("UPDATE sales_forms SET date=?,valid_until=?,memo=?,updated_at=?,partner_id=?,member_id=?,total=?,rounding_mode=?,content=? WHERE id=?", (date, valid_until, memo, stamp, partner, member, total, mode, content, identifier))
            else:
                prefix = {"quotation": "EST", "statement": "STM", "tax_reference": "TAX-REF"}[kind]
                number = f"{prefix}-{date.replace('-', '')}-{uuid4().hex[:10].upper()}"
                identifier = self.db.execute("INSERT INTO sales_forms(number,kind,date,valid_until,partner_id,member_id,total,rounding_mode,content,memo,user_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (number,kind,date,valid_until,partner,member,total,mode,content,memo,self.actor["id"],stamp,stamp)).lastrowid
            self._audit("update" if old else "create", "sales_form", identifier, {"kind": kind, "total": total, "non_posting": True})
            return identifier

    def delete_sales_form(self, identifier):
        with self._tx():
            row = self.db.execute("SELECT * FROM sales_forms WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise ValueError("문서를 찾을 수 없습니다.")
            self._require_capability(self._form_menu(row["kind"]), "delete")
            self.db.execute("DELETE FROM sales_forms WHERE id=?", (identifier,))
            self._audit("delete", "sales_form", identifier, {"number": row["number"], "non_posting": True})

    def offline_report(self, key, start, end, supplier_id=None, category="", search=""):
        config = {**REPORT_VIEWS, **SALES_VIEWS}.get(key)
        if not config:
            raise ValueError("보고서 종류를 확인하세요.")
        self.require_menu(key)
        start, end = day(start), day(end)
        if start > end:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
        _, period, group, _ = config
        where, args = ["d.status='posted'", "d.date BETWEEN ? AND ?"], [start, end]
        if key in SALES_VIEWS:
            where.append("d.kind IN ('sale','sale_return')")
        if supplier_id:
            where.append("l.supplier_id=?"); args.append(supplier_id)
        if category:
            if str(category).startswith('cat:'):
                try:path=self._category_path(int(str(category)[4:]))
                except (ValueError,TypeError):raise ValueError('분류를 다시 선택하세요.') from None
                for column,name in zip(('category','category_mid','category_small'),path):where.append('p.'+column+'=?');args.append(name)
            else:where.append("p.category=?"); args.append(text(category))
        if search:
            where.append("(p.code LIKE ? OR p.barcode LIKE ? OR l.product_name LIKE ? OR p.specification LIKE ?)")
            args.extend([f"%{text(search)}%"]*4)
        groups = {}
        sql = "SELECT l.*,d.date,d.kind,p.base_unit,p.category,COALESCE(s.name,'미지정 공급사') supplier_name FROM document_lines l JOIN documents d ON d.id=l.document_id JOIN products p ON p.id=l.product_id LEFT JOIN partners s ON s.id=l.supplier_id WHERE " + " AND ".join(where) + " ORDER BY d.date,d.id,l.id"
        for line in self.db.execute(sql, args):
            purchase = line["kind"].startswith("purchase")
            if group == "commission" and (purchase or not line["commission_bps"]):
                continue
            label = {"summary": "종합", "product": line["product_name"], "category": line["category"] or "미분류", "tax": line["category"] or "미분류", "supplier": line["supplier_name"], "commission": line["supplier_name"]}[group]
            identity = line["product_id"] if group == "product" else line["supplier_id"] if group in {"supplier", "commission"} else label
            unit = "g" if line["base_unit"] == "kg" else line["base_unit"]
            bucket = line["date"][:7] if period == "month" else line["date"]
            row = groups.setdefault((bucket, identity, unit), dict(period=bucket,label=label,unit=unit,purchase_qty=0,sale_qty=0,purchase_total=0,sale_total=0,cost=0,profit=0,taxable_sale_total=0,exempt_sale_total=0,commission_fee=0,vat=0,payable=0))
            sign = -1 if line["kind"].endswith("return") else 1
            qty = sign * line["base_qty"] * (1000 if line["base_unit"] == "kg" else 1)
            row["purchase_qty" if purchase else "sale_qty"] += qty
            row["purchase_total" if purchase else "sale_total"] += sign*line["total"]
            if not purchase:
                row["cost"] += sign*line["cost"]
                row["taxable_sale_total" if line["tax_mode"] == "taxable" else "exempt_sale_total"] += sign*line["total"]
                row["commission_fee"] += sign*line["commission_amount"]
        rows = list(groups.values())
        totals = {name: 0 for name in ("purchase_total", "sale_total", "cost", "profit", "taxable_sale_total", "exempt_sale_total", "commission_fee", "vat", "payable")}
        for row in rows:
            row["purchase_qty"], row["sale_qty"] = qtext(row["purchase_qty"]), qtext(row["sale_qty"])
            row["profit"] = row["sale_total"]-row["cost"]
            row["vat"] = rounded(Decimal(row["taxable_sale_total"])/11)
            row["payable"] = row["sale_total"]-row["commission_fee"]
            for name in totals:
                totals[name] += row[name]
        return {"rows": rows,"totals": totals,"start":start,"end":end,"basis":"확정 전표 실시간 합계 · 분류는 현재 상품장 · 부가세는 포함가 참고 계산"}

    def offline_report_filters(self, key):
        self.require_menu(key)
        if key not in REPORT_VIEWS and key not in SALES_VIEWS:
            raise ValueError("보고서 종류를 확인하세요.")
        return {"suppliers":[(r["name"],r["id"]) for r in self.db.execute("SELECT id,name FROM partners WHERE kind='supplier' ORDER BY name,id")],"categories":[(' / '.join(self._category_path(r['id'])),f"cat:{r['id']}") for r in self.db.execute('SELECT id FROM product_categories ORDER BY name,id')]}

    def sales_history(self,status,start,end,search='',member_id=None,user_id=None):
        key={'draft':'sales_held','cancelled':'sales_cancelled'}.get(status)
        if not key:raise ValueError('판매 이력 종류를 확인하세요.')
        self.require_menu(key)
        return self.documents('sale',start,end,status=status,search=search,member_id=member_id,user_id=user_id)

    def sales_period_comparison(self,key,start,end,supplier_id=None,category='',search=''):
        if key not in SALES_VIEWS:raise ValueError('판매조회 메뉴를 확인하세요.')
        self.require_menu(key);start,end=calendar_date.fromisoformat(day(start)),calendar_date.fromisoformat(day(end))
        if start>end or start.year<2:raise ValueError('조회 기간을 확인하세요.')
        from .household_planning import month_shift
        periods=[('선택 기간',start,end),('전일 대비',start-timedelta(days=1),end-timedelta(days=1)),('전주 대비',start-timedelta(days=7),end-timedelta(days=7)),('전월 대비',month_shift(start,-1),month_shift(end,-1))]
        rows=[];current=None
        for title,first,last in periods:
            total=self.offline_report(key,first.isoformat(),last.isoformat(),supplier_id,category,search)['totals']
            if current is None:current=total['sale_total']
            previous=total['sale_total']
            rows.append(dict(name=title,start=first.isoformat(),end=last.isoformat(),**total,difference=current-previous,
                             percent_change=(Decimal(current-previous)*100/previous).quantize(Decimal('.01')) if previous else None))
        return rows

    def basic_records(self, key, search=""):
        self.require_menu(key)
        if key not in BASIC_VIEWS:
            raise ValueError("기초관리 메뉴를 확인하세요.")
        if key in {"product_changes", "user_access"}:
            entity = "product" if key == "product_changes" else "user"
            return [dict(r) for r in self.db.execute("SELECT a.*,COALESCE(u.name,'시스템') user_name FROM audit a LEFT JOIN users u ON u.id=a.user_id WHERE a.entity=? AND (a.detail LIKE ? OR a.action LIKE ?) ORDER BY a.id DESC LIMIT 3000", (entity,*[f"%{text(search)}%"]*2))]
        if key == "product_units":
            return [dict(r) for r in self.db.execute("SELECT u.*,p.name product_name,p.code product_code,p.base_unit FROM product_units u JOIN products p ON p.id=u.product_id WHERE p.name LIKE ? OR p.code LIKE ? OR u.barcode LIKE ? ORDER BY p.name,u.id", [f"%{text(search)}%"]*3)]
        condition = "retirement_target=1" if key == "retirement" else "base_unit IN ('g','kg')"
        return [dict(r) for r in self.db.execute("SELECT * FROM products WHERE " + condition + " AND (name LIKE ? OR code LIKE ? OR barcode LIKE ? OR specification LIKE ?) ORDER BY name,id", [f"%{text(search)}%"]*4)]

    def member_view(self, key, start, end, member_id=None, search=""):
        self.require_menu(key)
        start, end = day(start), day(end)
        if start > end:
            raise ValueError("조회 기간을 확인하세요.")
        if key == "member_best":
            return self.best_members(start,end)
        if key not in MEMBER_VIEWS:
            raise ValueError("회원관리 메뉴를 확인하세요.")
        params, clause = [start,end], ""
        if member_id:
            clause = " AND x.member_id=?"; params.append(member_id)
        if key == "member_points":
            sql = "SELECT x.id,x.member_id,x.date,x.kind,x.delta,x.balance point_balance,x.reason,m.code,m.name FROM point_entries x JOIN members m ON m.id=x.member_id WHERE x.date BETWEEN ? AND ?"
        elif key == "member_transactions":
            sql = "SELECT x.*,m.code,m.name FROM documents x JOIN members m ON m.id=x.member_id WHERE x.date BETWEEN ? AND ? AND x.kind IN ('sale','sale_return')"
        elif key == "gift_history":
            sql = "SELECT x.*,m.code,m.name FROM gift_redemptions x JOIN members m ON m.id=x.member_id WHERE substr(x.created_at,1,10) BETWEEN ? AND ?"
        else:
            return [dict(r) for r in self.db.execute("SELECT x.*,m.code,m.name,p.name product_name FROM member_prices x JOIN members m ON m.id=x.member_id JOIN products p ON p.id=x.product_id WHERE (m.name LIKE ? OR m.code LIKE ? OR p.name LIKE ?)" + (" AND x.member_id=?" if member_id else "") + " ORDER BY m.name,p.name", [*[f"%{text(search)}%"]*3, *([member_id] if member_id else [])])]
        sql += clause + " AND (m.name LIKE ? OR m.code LIKE ?) ORDER BY x.id DESC"
        params.extend([f"%{text(search)}%"]*2)
        return [dict(r) for r in self.db.execute(sql, params)]
