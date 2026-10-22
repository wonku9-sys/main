from datetime import date
from decimal import Decimal
import pytest

from test_shared_network import crypto, network
from test_purchase_table_input import save_table
from pos2.purchase_import import plan_files


def test_file_table_import_keeps_amount_and_sale_snapshot_on_host_only(network,tmp_path):
    owner,_,(second,third),_,supplier,_,product=network
    source=tmp_path/'공유 표.xlsx'
    save_table(source,[['상품명','바코드','수량','단위','입수량','총수량','매입단가','판매단가','매입금액','메모'],
                       ['공유 상품','00001234','3','g','1','3','33.33','99.99','1','공유 입력']])
    files=plan_files([source],second.purchase_import_catalog(),supplier,date.today().isoformat())
    assert not files[0]['error'],files
    before=owner.products()[0]['stock_qty']
    result=second.import_purchase_drafts(files)
    record=third.document(result['created'][0])
    assert record['status']=='draft' and record['total']==1
    assert record['lines'][0]['entry']['sale_price']=='99.99'
    assert record['lines'][0]['entry']['memo']=='공유 입력'
    assert owner.products()[0]['stock_qty']==before
    assert third.import_purchase_drafts(files)==dict(created=[],existing=[record['id']])
    assert not second.private.db.execute('SELECT 1 FROM documents').fetchone()
    assert not third.private.db.execute('SELECT 1 FROM documents').fetchone()


def test_other_pc_catalog_changes_invalidate_analyzed_table_atomically(network,tmp_path):
    owner,_,(second,third),_,supplier,_,product=network
    source=tmp_path/'변경 검사.tsv'
    save_table(source,[['상품명','바코드','수량','매입단가','판매단가'],['공유 상품','00001234',100,100,200]])
    files=plan_files([source],second.purchase_import_catalog(),supplier,date.today().isoformat())
    assert not files[0]['error']
    current=next(p for p in third.products() if p['id']==product)
    third.save_product(dict(name='다른 PC 수정',_expected_token=current['_edit_token']),product)
    before=len(owner.documents())
    with pytest.raises(ValueError,match='변경'):second.import_purchase_drafts(files)
    assert len(owner.documents())==before
