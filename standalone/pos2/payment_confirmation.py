"""Supplier ledger's O confirmation mark, independent from payment amounts."""
import hmac
import json

from .shared_protocol import fingerprint
from .payment_closing import PaymentClosingMixin


class PaymentConfirmationMixin(PaymentClosingMixin):
    def _ledger_confirmation(self, partner_id, source_type, source_id, cache=None):
        tables={'document':'documents','payment':'payments','settlement':'supplier_settlements'}
        if source_type not in tables or type(source_id) is not int:
            raise ValueError('전표별 거래내역에서 확인할 행을 선택하세요.')
        row=cache['records'].get((source_type,source_id)) if cache else self.db.execute(f'SELECT * FROM {tables[source_type]} WHERE id=? AND partner_id=?',(source_id,partner_id)).fetchone()
        if not row or source_type=='document' and (row['status']!='posted' or row['kind'] not in {'purchase','purchase_return'}) or source_type!='document' and row['voided']:
            raise ValueError('유효한 공급사 거래내역만 결제확인 표시할 수 있습니다.')
        if source_type=='payment' and row['supplier_settlement_id']:
            return self._ledger_confirmation(partner_id,'settlement',row['supplier_settlement_id'],cache)
        last=cache['marks'].get((source_type,source_id)) if cache else self.db.execute("SELECT id,detail FROM audit WHERE action='supplier_ledger_checked' AND json_extract(detail,'$.partner_id')=? AND json_extract(detail,'$.source_type')=? AND json_extract(detail,'$.source_id')=? ORDER BY id DESC LIMIT 1",(partner_id,source_type,source_id)).fetchone()
        checked=bool(json.loads(last['detail'])['checked']) if last else False
        return dict(source_type=source_type,source_id=source_id,checked=checked,
                    confirmation_state=fingerprint(dict(record=dict(row),last=last['id'] if last else None,restore=cache['restore'] if cache else self._current_restore_token())))

    def supplier_ledger(self, partner_id, start='', end=''):
        self._require('trade');self.require_menu('payments')
        partner=self.db.execute("SELECT id FROM partners WHERE id=? AND kind='supplier'",(partner_id,)).fetchone()
        if not partner:raise ValueError('공급사를 선택하세요.')
        result=self.ledger(partner_id,start,end)
        cache=dict(records={},marks={},restore=self._current_restore_token())
        for kind,table in (('document','documents'),('payment','payments'),('settlement','supplier_settlements')):
            for record in self.db.execute(f'SELECT * FROM {table} WHERE partner_id=?',(partner_id,)):
                cache['records'][(kind,record['id'])]=dict(record)
        for mark in self.db.execute("SELECT id,detail FROM audit WHERE action='supplier_ledger_checked' AND json_extract(detail,'$.partner_id')=? ORDER BY id DESC",(partner_id,)):
            detail=json.loads(mark['detail']);cache['marks'].setdefault((detail['source_type'],detail['source_id']),dict(mark))
        for row in result['entries']:
            key=next(((kind,row[field]) for kind,field in (('settlement','settlement_id'),('payment','payment_id'),('document','document_id')) if row.get(field)),None)
            if key:row.update(self._ledger_confirmation(partner_id,*key,cache))
        return result

    def set_supplier_ledger_checked(self, partner_id, source_type, source_id, checked, expected_state):
        with self._tx():
            self._require('trade');self._require_capability('payments','create')
            if type(checked) is not bool:raise ValueError('결제확인은 표시/해제만 가능합니다.')
            if not self.db.execute("SELECT 1 FROM partners WHERE id=? AND kind='supplier'",(partner_id,)).fetchone():raise ValueError('공급사를 선택하세요.')
            current=self._ledger_confirmation(partner_id,source_type,source_id)
            if not isinstance(expected_state,str) or not hmac.compare_digest(expected_state,current['confirmation_state']):
                raise ValueError('선택한 거래 또는 확인 상태가 바뀌었습니다. 다시 조회하세요.')
            if checked!=current['checked']:
                self._audit('supplier_ledger_checked','ledger_confirmation',None,
                    dict(partner_id=partner_id,source_type=current['source_type'],source_id=current['source_id'],checked=checked))
            return self._ledger_confirmation(partner_id,current['source_type'],current['source_id'])
