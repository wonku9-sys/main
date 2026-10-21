"""Encrypted FP114-inspired household planning. Never posts bank transactions."""
import calendar
from datetime import date
from decimal import Decimal, ROUND_UP

from .common import day, money, text

PLAN_KINDS = {'asset', 'debt', 'goal', 'category_budget', 'category_group', 'forecast', 'template', 'report_preset'}
REPORTS = {'daily':'일자별 거래내역','account':'계정별 거래현황','category':'항목별 수입·지출','payee':'거래처별 현황',
           'owner':'소유자별 거래','tag':'그룹·태그별 거래','top_amount':'수입·지출 금액 Top 10','top_count':'수입·지출 빈도 Top 10'}
ASSET_TYPES = {'cash': '현금성', 'deposit': '예·적금', 'property': '부동산·보증금', 'investment': '투자', 'other': '기타 자산'}
EXPENSE_GROUPS = {'living': '생활비', 'education': '자녀·자기 교육비', 'tax': '세금·사회보험', 'saving': '저축·투자·보장보험', 'other': '기타 생활비'}


def month_shift(value, offset):
    year, month = divmod(value.year * 12 + value.month - 1 + offset, 12)
    return date(year, month + 1, min(value.day, calendar.monthrange(year, month + 1)[1]))


class HouseholdPlanningMixin:
    def household_plans(self, key, kind=''):
        if kind and kind not in PLAN_KINDS: raise ValueError('재무 계획 종류를 확인하세요.')
        return [r for r in self._finance_records(key, 'plans') if not kind or r['kind'] == kind]

    def save_household_plan(self, key, data, identifier=None):
        with self._tx():
            kind = data.get('kind')
            if kind not in PLAN_KINDS: raise ValueError('재무 계획 종류를 확인하세요.')
            old = next((r for r in self.household_plans(key) if r['id'] == identifier), None)
            if identifier and (not old or old['kind'] != kind): raise ValueError('기존 항목의 종류는 변경할 수 없습니다.')
            content = dict(kind=kind, name=text(data.get('name'), '이름·분류', True, 100),
                           amount=money(data.get('amount', 0)), memo=text(data.get('memo', ''), '메모', maximum=2000))
            if kind in {'asset', 'debt'}:
                content['date'] = day(data.get('date'))
                content['asset_type'] = data.get('asset_type', 'other')
                if content['asset_type'] not in ASSET_TYPES: raise ValueError('자산 종류를 확인하세요.')
            elif kind == 'goal':
                content['target_date'] = day(data.get('target_date'))
                content['saved_amount'] = money(data.get('saved_amount', 0))
                account = str(data.get('account_id') or '')
                if account and not any(r['id'] == account for r in self.household_accounts(key)): raise ValueError('목표 연결 통장을 확인하세요.')
                content['account_id'] = account
                if content['amount'] <= 0: raise ValueError('목표 금액은 0보다 커야 합니다.')
            elif kind == 'category_budget':
                month = str(data.get('month', ''))
                if len(month) != 7 or day(month + '-01')[:7] != month: raise ValueError('예산 월은 YYYY-MM 형식입니다.')
                content['month'] = month
            elif kind == 'category_group':
                content['group'] = data.get('group')
                if content['group'] not in EXPENSE_GROUPS: raise ValueError('생활비 구분을 확인하세요.')
            elif kind == 'template':
                content['entry_kind']=data.get('entry_kind','expense')
                if content['entry_kind'] not in {'income','expense'}:raise ValueError('거래틀의 수입·지출 구분을 확인하세요.')
                content['category']=text(data.get('category','기타'),'분류',True,100)
                content['title']=text(data.get('title',content['name']),'거래 내용',True,200)
                content['payee']=text(data.get('payee',''),'거래처',maximum=100)
            elif kind == 'report_preset':
                content['view']=data.get('view','category')
                if content['view'] not in REPORTS:raise ValueError('보고서 종류를 확인하세요.')
                content['category']=text(data.get('category',''),'분류',maximum=100)
                content['search']=text(data.get('search',''),'검색',maximum=200)
                content['account_id']=str(data['account_id']) if data.get('account_id') is not None else None
                if content['account_id'] and not any(r['id']==content['account_id'] for r in self.household_accounts(key)):raise ValueError('계정을 확인하세요.')
            if kind in {'category_budget', 'category_group', 'forecast'}:
                duplicate = next((r for r in self.household_plans(key, kind) if r['id'] != identifier and
                                  (kind == 'forecast' or r['name'] == content['name'] and r.get('month') == content.get('month'))), None)
                if duplicate: raise ValueError('같은 항목이 있습니다. 기존 항목을 선택해 수정하세요.')
            return self._finance_put(key, 'plans', content, identifier)

    def delete_household_plan(self, key, identifier):
        with self._tx():
            self._require_household_key(key); self._require_capability('household', 'delete')
            if not self.db.execute('DELETE FROM household_plans WHERE id=? AND user_id=?', (identifier, self.actor['id'])).rowcount:
                raise ValueError('재무 계획을 찾을 수 없습니다.')
            self._audit('delete', 'household_plan', None, {})

    def split_household_entry(self,key,identifier,parts):
        with self._tx():
            self._require_household_key(key);self._require_capability('household','edit');self._require_capability('household','create')
            old=next((r for r in self._household_records(key) if r['id']==identifier),None)
            if not old:raise ValueError('나눌 거래를 찾을 수 없습니다.')
            if any(old.get(name) for name in ('vehicle_id','fixed_rule_id','vehicle_obligation_id','split_group')):
                raise ValueError('차량·고정비·이미 나눈 거래는 이 메뉴에서 분할할 수 없습니다.')
            if not isinstance(parts,list) or not 2<=len(parts)<=30:raise ValueError('세부 거래는 2~30개로 나누세요.')
            clean=[dict(category=text(p.get('category'),'분류',True,100),title=text(p.get('title'),'내용',True,200),amount=money(p.get('amount'),positive=True)) for p in parts]
            if sum(p['amount'] for p in clean)!=old['amount']:raise ValueError('세부 금액 합계가 원래 거래 금액과 정확히 같아야 합니다.')
            from uuid import uuid4
            group=uuid4().hex;results=[]
            for index,part in enumerate(clean):
                content=dict(old,**part,split_group=group,split_original_amount=old['amount'])
                content.pop('id',None)
                results.append(self._household_put_entry(key,content,identifier if index==0 else None,old if index==0 else None))
            return results

    def household_custom_report(self,key,start,end,view='category',account_id=None,category='',search=''):
        start,end=day(start),day(end)
        if view not in REPORTS:raise ValueError('보고서 종류를 확인하세요.')
        if start>end:raise ValueError('조회 기간을 확인하세요.')
        accounts={r['id']:r for r in self.household_accounts(key)}
        if account_id is not None and account_id!='' and account_id not in accounts:raise ValueError('선택한 계정을 확인하세요.')
        report=self.household_report(key,start,end,category,search,account_id)
        entries=[r for r in report['rows'] if r['kind'] in {'income','expense'}]
        groups={}
        for r in entries:
            labels=([r['date']] if view=='daily' else [r['account_name']] if view=='account' else
                    [r.get('payee') or r.get('vehicle_vendor') or '거래처 미지정'] if view=='payee' else
                    [accounts.get(r.get('account_id'),{}).get('owner') or '본인'] if view=='owner' else
                    r.get('tags') or ['태그 없음'] if view=='tag' else [r['category']])
            for label in labels:
                identity=(r['kind'],label);bucket=groups.setdefault(identity,dict(name=label,kind=r['kind'],amount=0,count=0,entry_ids=[]))
                bucket['amount']+=r['amount'];bucket['count']+=1;bucket['entry_ids'].append(r['id'])
        rows=list(groups.values())
        if view.startswith('top_'):
            rank='count' if view=='top_count' else 'amount'
            rows=[r for kind in ('income','expense') for r in sorted((r for r in rows if r['kind']==kind),key=lambda r:(-r[rank],r['name']))[:10]]
        else:rows.sort(key=lambda r:(r['kind'],r['name']))
        return dict(rows=rows,entries=entries,income_total=report['income_total'],expense_total=report['expense_total'],
                    balance=report['income_total']-report['expense_total'],opening_balance=report['opening_balance'],closing_balance=report['closing_balance'])

    def household_annual_report(self, key, year):
        try: year = int(year); date(year, 1, 1)
        except (ValueError, TypeError, OverflowError): raise ValueError('연도를 확인하세요.') from None
        records = self._household_records(key); budgets = self._finance_records(key, 'budgets')
        rows = []
        for month in range(1, 13):
            prefix = f'{year:04}-{month:02}'
            own = [r for r in records if r['date'].startswith(prefix)]
            income = sum(r['amount'] for r in own if r['kind'] == 'income')
            expense = sum(r['amount'] for r in own if r['kind'] == 'expense')
            fixed = sum(r['amount'] for r in own if r['kind'] == 'expense' and r.get('fixed_rule_id'))
            budget = next((r['amount'] for r in budgets if r['month'] == prefix), 0)
            rows.append(dict(month=prefix, income_total=income, expense_total=expense, balance=income-expense,
                             fixed_total=fixed, variable_total=expense-fixed, budget_total=budget, available_total=budget-expense))
        return rows

    def household_financial_overview(self, key, start, end):
        start, end = day(start), day(end)
        if start > end: raise ValueError('조회 기간을 확인하세요.')
        dashboard = self.household_dashboard(key, start, end); plans = self.household_plans(key)
        accounts = dashboard['accounts']; valuations = [r for r in plans if r['kind'] in {'asset', 'debt'} and r['date'] <= end]
        cash = sum(max(0, r['balance']) for r in accounts if r.get('account_type') not in {'deposit','investment'})
        cash += sum(r['amount'] for r in valuations if r['kind'] == 'asset' and r['asset_type'] == 'cash')
        locked = sum(r['amount'] for r in valuations if r['kind'] == 'asset' and r['asset_type'] != 'cash')
        locked += sum(max(0, r['balance']) for r in accounts if r.get('account_type') in {'deposit','investment'})
        debts = sum(r['amount'] for r in valuations if r['kind'] == 'debt') + sum(max(0, -r['balance']) for r in accounts)
        goals = []
        for r in plans:
            if r['kind'] != 'goal': continue
            saved = max(0, next((a['balance'] for a in accounts if a['id'] == r['account_id']), 0)) if r['account_id'] else r['saved_amount']
            gap = max(0, r['amount'] - saved); target = date.fromisoformat(r['target_date']); current = date.fromisoformat(end)
            months = max(1, (target.year-current.year)*12 + target.month-current.month)
            goals.append(dict(r, saved_amount=saved, gap=gap, monthly_saving=int((Decimal(gap)/months).to_integral_value(rounding=ROUND_UP)),
                              percent=(Decimal(saved)*100/r['amount']).quantize(Decimal('0.01')), overdue=target<current and gap>0))
        expenses = [r for r in self._household_records(key) if r['kind'] == 'expense' and start <= r['date'] <= end]
        group_rules = {r['name']: r['group'] for r in plans if r['kind'] == 'category_group'}
        default_groups = {'교육': 'education', '교육비': 'education', '자녀교육비': 'education', '세금공과금': 'tax',
                          '세금·사회보험': 'tax', '저축': 'saving', '저축·투자': 'saving', '보장성보험': 'saving'}
        groups = {code: 0 for code in EXPENSE_GROUPS}
        for r in expenses: groups[group_rules.get(r['category'], default_groups.get(r['category'], 'living'))] += r['amount']
        total = sum(groups.values()); necessary = total - groups['tax'] - groups['saving']
        category_budgets = []
        for r in plans:
            if r['kind'] != 'category_budget': continue
            used = sum(e['amount'] for e in self._household_records(key) if e['kind'] == 'expense' and e['date'][:7] == r['month'] and e['date'] <= end and e['category'] == r['name'])
            if r['month'] < start[:7] or r['month'] > end[:7]: continue
            category_budgets.append(dict(r, expense_total=used, available_total=r['amount']-used,
                                        percent=(Decimal(used)*100/r['amount']).quantize(Decimal('0.01')) if r['amount'] else None))
        return dict(cash_assets=cash, locked_assets=locked, asset_total=cash+locked, debt_total=debts, net_assets=cash+locked-debts,
                    valuations=valuations, goals=goals, category_budgets=category_budgets,
                    expense_groups=[dict(name=EXPENSE_GROUPS[k], amount=v) for k,v in groups.items()],
                    necessary_total=necessary, living_total=necessary-groups['education'],
                    income_total=dashboard['income_total'], expense_total=dashboard['expense_total'])

    def household_cash_forecast(self, key, as_of, months=12):
        value = date.fromisoformat(day(as_of))
        if value > date.today(): raise ValueError('예측 시작일은 오늘까지 지정하세요.')
        if type(months) is not int or not 1 <= months <= 12: raise ValueError('예측 기간은 1~12개월입니다.')
        balance = self.household_dashboard(key, value.isoformat(), value.isoformat())['balance']
        expected = next((r['amount'] for r in self.household_plans(key, 'forecast')), 0)
        rules = self.household_fixed_costs(key); rows = []
        # Whole future calendar months only. No partial-current-month estimate.
        for offset in range(1, months+1):
            month = month_shift(value.replace(day=1), offset); costs = 0
            for rule in rules:
                due = month.replace(day=min(rule['monthly_day'], calendar.monthrange(month.year,month.month)[1])).isoformat()
                if rule['active'] and rule['start_date'] <= due and (not rule['end_date'] or due <= rule['end_date']): costs += rule['amount']
            balance += expected-costs
            rows.append(dict(month=month.strftime('%Y-%m'), income_total=expected, expense_total=costs, projected_balance=balance))
        return rows
