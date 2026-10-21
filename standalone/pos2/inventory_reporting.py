"""Read-only inventory drill-downs; manual inventory chapter pp.90–98."""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from .common import text

GROUP_MENUS={'products':'inventory','categories':'inventory_categories','suppliers':'inventory_suppliers','monthly':'inventory_monthly'}
AMOUNTS=('stock_cost','purchase_total','sale_total','taxable_total','exempt_total','supply_value','vat')

def minor_value(raw_qty,price,basis):
    return int((Decimal(raw_qty)*price/1000/max(1,basis)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))

def summarize(rows):
    result={key:sum(row.get(key,0) for row in rows) for key in AMOUNTS}
    quantities=defaultdict(Decimal)
    for row in rows:quantities[row['base_unit']]+=Decimal(row['stock_qty'])
    result.update(item_count=len(rows),quantities={unit:str(value) for unit,value in sorted(quantities.items())})
    return result

def group_records(products,group,selected_path=(),children=False):
    if group=='products' or group=='categories' and len(selected_path)>=3:return [dict(row,row_kind='product',label=row['name'],depth=0) for row in products]
    buckets=defaultdict(list)
    for row in products:
        if group=='suppliers':buckets[(row.get('supplier_id',row.get('supplier_name')),row.get('supplier_name') or '미지정')].append(row)
        else:
            path=tuple(row['path']);depth=min(len(selected_path)+1,len(path))
            for length in range(max(1,depth),len(path)+1) if children else (depth,):buckets[path[:length]].append(row)
    result=[]
    for key,rows in sorted(buckets.items(),key=lambda item:str(item[0])):
        path=key if group=='categories' else ()
        record=dict(summarize(rows),row_kind='group',path=list(path),label=key[-1],depth=max(0,len(path)-len(selected_path)-1))
        if group=='suppliers':record.update(supplier_id=key[0],supplier_code=rows[0].get('supplier_code',''),business_no=rows[0].get('business_no',''))
        result.append(record)
        if children and group=='categories':
            result.extend(dict(row,row_kind='product',label=row['name'],depth=len(path)-len(selected_path)) for row in rows if tuple(row['path'])==key)
    return result

class InventoryReportingMixin:
    def inventory_status(self,group='products',category_path=None,supplier_id=None,search='',include_inactive=False,show_children=False,stock_filter='all',valuation='catalog',month='',monthly_group='categories'):
        if group not in GROUP_MENUS:raise ValueError('재고 조회 구분을 확인하세요.')
        self._require('inventory');self.require_menu(GROUP_MENUS[group])
        if stock_filter not in {'all','nonzero','positive','zero','negative'} or valuation not in {'catalog','average'}:raise ValueError('재고 조회 조건을 확인하세요.')
        if monthly_group not in {'products','categories','suppliers'}:raise ValueError('월말 조회 구분을 확인하세요.')
        path=tuple(category_path or ())
        if len(path)>3 or not all(isinstance(value,str) for value in path):raise ValueError('분류 경로를 확인하세요.')
        query=text(search).casefold();products=[];closed=None
        if group=='monthly':
            closed=self.db.execute('SELECT * FROM inventory_closes WHERE month=?',(month,)).fetchone()
            if closed:
                for record in self.db.execute('SELECT * FROM inventory_close_lines WHERE close_id=? ORDER BY product_code,id',(closed['id'],)):
                    row=dict(record)
                    products.append(dict(row,id=row['product_id'],code=row['product_code'],name=row['product_name'],path=[row['category'] or '미분류'],active=True,tracked=True,stock_qty=str(Decimal(row['stock_qty'])/1000)))
        else:
            counts={row['product_id']:row['last_count'] for row in self.db.execute("SELECT l.product_id,MAX(c.date) AS last_count FROM inventory_count_lines l JOIN inventory_counts c ON c.id=l.count_id WHERE c.status='applied' GROUP BY l.product_id")}
            for record in self.db.execute("SELECT p.*,s.name AS supplier_name,s.code AS supplier_code,s.business_no FROM products p LEFT JOIN partners s ON s.id=p.supplier_id WHERE p.tracked=1 ORDER BY p.code"):
                row=dict(record);raw_qty=row['stock_qty']
                row['path']=[]
                for key in ('category','category_mid','category_small'):
                    if not row.get(key):break
                    row['path'].append(row[key])
                if not row['path']:row['path']=['미분류']
                row['stock_qty']=str(Decimal(raw_qty)/1000);row['last_count']=counts.get(row['id'],'')
                row['purchase_total']=minor_value(raw_qty,row['purchase_price'],row['price_basis'])
                row['sale_total']=minor_value(raw_qty,row['sale_price'],row['price_basis'])
                basis=row['purchase_total'] if valuation=='catalog' else row['stock_cost']
                row['taxable_total']=basis if row['tax_mode']=='taxable' else 0;row['exempt_total']=basis if row['tax_mode']!='taxable' else 0
                row['supply_value']=int((Decimal(row['taxable_total'])/Decimal('1.1')).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                row['vat']=row['taxable_total']-row['supply_value']
                products.append(row)
        categories=[dict(id=row['id'],path=self._category_path(row['id'])) for row in self.db.execute('SELECT id FROM product_categories ORDER BY level,id')]
        suppliers=[dict(row) for row in self.db.execute("SELECT DISTINCT s.id,s.code,s.name FROM partners s JOIN products p ON p.supplier_id=s.id WHERE s.kind='supplier' ORDER BY s.code")]
        months=[dict(row) for row in self.db.execute('SELECT id,month,created_at FROM inventory_closes ORDER BY month DESC')]
        if group=='monthly':
            categories=[dict(id=index,path=list(category)) for index,category in enumerate(sorted({tuple(row['path']) for row in products}))]
            suppliers=list({row['supplier_name']:dict(id=row['supplier_name'],code='',name=row['supplier_name']) for row in products}.values())
        selected=[]
        for row in products:
            quantity=Decimal(row['stock_qty'])
            if not include_inactive and not row['active']:continue
            if path and tuple(row['path'][:len(path)])!=path:continue
            if supplier_id is not None:
                match=row.get('supplier_name','') if group=='monthly' else (row.get('supplier_id') or 0)
                if match!=supplier_id:continue
            if query not in ' '.join(str(row.get(key,'')) for key in ('code','name','barcode','specification','supplier_name')).casefold():
                if group=='monthly' or not self.db.execute('SELECT 1 FROM product_units WHERE product_id=? AND LOWER(barcode) LIKE ?',(row['id'],'%'+query+'%')).fetchone():continue
            if stock_filter=='nonzero' and quantity==0 or stock_filter=='positive' and quantity<=0 or stock_filter=='zero' and quantity!=0 or stock_filter=='negative' and quantity>=0:continue
            selected.append(row)
        effective=monthly_group if group=='monthly' else group
        return {'rows':group_records(selected,effective,path,show_children and group!='monthly'),'products':selected,'totals':summarize(selected),'filters':{'categories':categories,'suppliers':suppliers,'months':months},'closed_at':closed['created_at'] if closed else '','snapshot':group=='monthly','valuation':valuation}
