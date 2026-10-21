"""Readable old/new audit values; never estimates a missing historical value."""
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
import json
from datetime import datetime


def audit_rows(records,labels):
    output=[]
    for record in records:
        timestamp=record['at']
        try:timestamp=datetime.fromisoformat(timestamp).astimezone().strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError,TypeError):pass
        detail=record.get('detail',{})
        if isinstance(detail,str):
            try:detail=json.loads(detail)
            except (ValueError,TypeError):detail={}
        if not isinstance(detail,dict):detail={}
        changes=detail.get('changes',{})
        if record['action']=='create' or not isinstance(changes,dict) or not changes:
            title='상품 등록' if record['action']=='create' else record['action']
            new=detail.get('name') or changes.get('name',{}).get('new','')
            output.append([title,'—',str(new),'—','—',timestamp,record.get('user_name') or '시스템',record['action']]);continue
        for key,change in changes.items():
            if key in {'created_at','updated_at'} or not isinstance(change,dict):continue
            old,new=change.get('old'),change.get('new');delta=ratio='—'
            if key in {'purchase_price','sale_price','price','min_qty','factor'}:
                try:
                    before=Decimal(str(old));after=Decimal(str(new))
                    if key in {'min_qty','factor'}:
                        if type(old) is int:before/=1000
                        if type(new) is int:after/=1000
                    old,new=before,after;delta=after-before
                    ratio=((delta/abs(before))*100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP) if before else '— (기준 0)'
                except (InvalidOperation,ValueError,TypeError):pass
            def display(value):
                if value is None:return '—'
                if key=='tax_mode':return {'taxable':'과 · 과세','exempt':'면 · 면세'}.get(value,str(value))
                if key in {'active','tracked','retirement_target'}:return '사용' if value else '해제'
                return value
            output.append([labels.get(key,key),display(old),display(new),delta,ratio,timestamp,record.get('user_name') or '시스템',record['action']])
    return output
