"""New schema; deliberately independent from the legacy application's database."""
from .suppliers import SUPPLIER_SCHEMA
from .offline_features import OFFLINE_SCHEMA
from .diary import DIARY_SCHEMA
from .household import HOUSEHOLD_SCHEMA
from .health import HEALTH_SCHEMA
from .email_recovery import EMAIL_SCHEMA

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','staff')),
 permissions TEXT NOT NULL DEFAULT '[]', active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE TABLE IF NOT EXISTS partners (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('supplier','customer')),
 code TEXT NOT NULL, name TEXT NOT NULL, business_no TEXT NOT NULL DEFAULT '',
 contact TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '', bank TEXT NOT NULL DEFAULT '',
 account TEXT NOT NULL DEFAULT '', account_holder TEXT NOT NULL DEFAULT '', memo TEXT NOT NULL DEFAULT '',
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 opening_balance INTEGER NOT NULL DEFAULT 0 CHECK(ABS(opening_balance)<=9000000000000),
 opening_date TEXT NOT NULL,
 supplier_mode TEXT NOT NULL DEFAULT 'direct' CHECK(supplier_mode IN ('direct','commission')),
 commission_bps INTEGER NOT NULL DEFAULT 0 CHECK(commission_bps BETWEEN 0 AND 10000), UNIQUE(kind,code)
);
CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, barcode TEXT NOT NULL DEFAULT '',
 name TEXT NOT NULL, receipt_name TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '',
 category_mid TEXT NOT NULL DEFAULT '', category_small TEXT NOT NULL DEFAULT '',
 specification TEXT NOT NULL DEFAULT '', base_unit TEXT NOT NULL DEFAULT 'kg',
 tax_mode TEXT NOT NULL DEFAULT 'exempt' CHECK(tax_mode IN ('exempt','taxable')),
 tracked INTEGER NOT NULL DEFAULT 1 CHECK(tracked IN (0,1)), active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 supplier_id INTEGER REFERENCES partners(id) ON DELETE RESTRICT,
 purchase_price INTEGER NOT NULL DEFAULT 0 CHECK(purchase_price BETWEEN 0 AND 9000000000000),
 sale_price INTEGER NOT NULL DEFAULT 0 CHECK(sale_price BETWEEN 0 AND 9000000000000),
 min_qty INTEGER NOT NULL DEFAULT 0 CHECK(min_qty BETWEEN 0 AND 9000000000000),
 stock_qty INTEGER NOT NULL DEFAULT 0 CHECK(stock_qty BETWEEN 0 AND 9000000000000),
 stock_cost INTEGER NOT NULL DEFAULT 0 CHECK(stock_cost BETWEEN 0 AND 9000000000000),
 origin TEXT NOT NULL DEFAULT '', warehouse TEXT NOT NULL DEFAULT '', shelf TEXT NOT NULL DEFAULT '',
 keywords TEXT NOT NULL DEFAULT '', memo TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 retirement_target INTEGER NOT NULL DEFAULT 0 CHECK(retirement_target IN (0,1)),
 price_basis INTEGER NOT NULL DEFAULT 1 CHECK(price_basis IN (1,100))
);
CREATE UNIQUE INDEX IF NOT EXISTS product_barcode_unique ON products(barcode) WHERE barcode<>'';
CREATE TABLE IF NOT EXISTS product_units (
 id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
 name TEXT NOT NULL, barcode TEXT NOT NULL DEFAULT '', factor INTEGER NOT NULL CHECK(factor BETWEEN 1 AND 9000000000000),
 purchase_price INTEGER NOT NULL DEFAULT 0 CHECK(purchase_price BETWEEN 0 AND 9000000000000),
 sale_price INTEGER NOT NULL DEFAULT 0 CHECK(sale_price BETWEEN 0 AND 9000000000000),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), UNIQUE(product_id,name)
);
CREATE UNIQUE INDEX IF NOT EXISTS unit_barcode_unique ON product_units(barcode) WHERE barcode<>'';
CREATE TRIGGER IF NOT EXISTS product_cross_barcode_insert BEFORE INSERT ON products
 WHEN NEW.barcode<>'' AND EXISTS(SELECT 1 FROM product_units WHERE barcode=NEW.barcode)
 BEGIN SELECT RAISE(ABORT,'이미 등록된 확장단위 바코드입니다.'); END;
CREATE TRIGGER IF NOT EXISTS product_cross_barcode_update BEFORE UPDATE OF barcode ON products
 WHEN NEW.barcode<>'' AND EXISTS(SELECT 1 FROM product_units WHERE barcode=NEW.barcode)
 BEGIN SELECT RAISE(ABORT,'이미 등록된 확장단위 바코드입니다.'); END;
CREATE TRIGGER IF NOT EXISTS unit_cross_barcode_insert BEFORE INSERT ON product_units
 WHEN NEW.barcode<>'' AND EXISTS(SELECT 1 FROM products WHERE barcode=NEW.barcode)
 BEGIN SELECT RAISE(ABORT,'이미 등록된 상품 바코드입니다.'); END;
CREATE TRIGGER IF NOT EXISTS unit_cross_barcode_update BEFORE UPDATE OF barcode ON product_units
 WHEN NEW.barcode<>'' AND EXISTS(SELECT 1 FROM products WHERE barcode=NEW.barcode)
 BEGIN SELECT RAISE(ABORT,'이미 등록된 상품 바코드입니다.'); END;
CREATE TABLE IF NOT EXISTS documents (
 id INTEGER PRIMARY KEY, number TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL CHECK(kind IN ('purchase','sale','purchase_return','sale_return')),
 date TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('draft','posted','cancelled')),
 partner_id INTEGER NOT NULL REFERENCES partners(id) ON DELETE RESTRICT,
 member_id INTEGER REFERENCES members(id) ON DELETE RESTRICT,
 source_id INTEGER REFERENCES documents(id) ON DELETE RESTRICT,
 total INTEGER NOT NULL DEFAULT 0 CHECK(total BETWEEN 0 AND 9000000000000),
 cash_paid INTEGER NOT NULL DEFAULT 0 CHECK(cash_paid BETWEEN 0 AND 9000000000000),
 points_used INTEGER NOT NULL DEFAULT 0 CHECK(points_used BETWEEN 0 AND 9000000000000),
 points_earned INTEGER NOT NULL DEFAULT 0 CHECK(points_earned BETWEEN 0 AND 9000000000000),
 memo TEXT NOT NULL DEFAULT '', user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL, cancel_reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS document_lines (
 id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
 unit_id INTEGER REFERENCES product_units(id) ON DELETE RESTRICT,
 product_name TEXT NOT NULL, unit_name TEXT NOT NULL,
 factor INTEGER NOT NULL CHECK(factor>0), input_qty INTEGER NOT NULL CHECK(input_qty>0),
 base_qty INTEGER NOT NULL CHECK(base_qty>0), unit_price INTEGER NOT NULL CHECK(unit_price>=0),
 total INTEGER NOT NULL CHECK(total>=0), cost INTEGER NOT NULL DEFAULT 0 CHECK(cost>=0),
 source_line_id INTEGER REFERENCES document_lines(id) ON DELETE RESTRICT,
 supplier_id INTEGER REFERENCES partners(id) ON DELETE RESTRICT,
 commission_bps INTEGER NOT NULL DEFAULT 0 CHECK(commission_bps BETWEEN 0 AND 10000),
 commission_amount INTEGER NOT NULL DEFAULT 0 CHECK(commission_amount>=0),
 tax_mode TEXT NOT NULL DEFAULT 'exempt' CHECK(tax_mode IN ('exempt','taxable'))
);
CREATE TABLE IF NOT EXISTS supplier_settlements (
 id INTEGER PRIMARY KEY, partner_id INTEGER NOT NULL REFERENCES partners(id) ON DELETE RESTRICT,
 date TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount BETWEEN 1 AND 9000000000000),
 opening_amount INTEGER NOT NULL DEFAULT 0 CHECK(opening_amount BETWEEN 0 AND amount),
 method TEXT NOT NULL CHECK(method IN ('cash','transfer')), memo TEXT NOT NULL DEFAULT '',
 voided INTEGER NOT NULL DEFAULT 0 CHECK(voided IN (0,1)),
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
 id INTEGER PRIMARY KEY, partner_id INTEGER NOT NULL REFERENCES partners(id) ON DELETE RESTRICT,
 document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
 date TEXT NOT NULL, amount INTEGER NOT NULL CHECK(ABS(amount)<=9000000000000),
 method TEXT NOT NULL CHECK(method IN ('cash','transfer')), memo TEXT NOT NULL DEFAULT '',
 voided INTEGER NOT NULL DEFAULT 0 CHECK(voided IN (0,1)),
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT, created_at TEXT NOT NULL,
 supplier_settlement_id INTEGER REFERENCES supplier_settlements(id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS stock_events (
 id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
 document_id INTEGER REFERENCES documents(id) ON DELETE RESTRICT, date TEXT NOT NULL,
 kind TEXT NOT NULL, qty_delta INTEGER NOT NULL CHECK(ABS(qty_delta)<=9000000000000),
 cost_delta INTEGER NOT NULL CHECK(ABS(cost_delta)<=9000000000000),
 balance_qty INTEGER NOT NULL CHECK(balance_qty BETWEEN 0 AND 9000000000000),
 balance_cost INTEGER NOT NULL CHECK(balance_cost BETWEEN 0 AND 9000000000000),
 reason TEXT NOT NULL DEFAULT '', user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, at TEXT NOT NULL, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
 action TEXT NOT NULL, entity TEXT NOT NULL, entity_id INTEGER, detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS code_sequences (
 name TEXT PRIMARY KEY, last_value INTEGER NOT NULL CHECK(last_value>=0)
);
CREATE TABLE IF NOT EXISTS product_categories (
 id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES product_categories(id) ON DELETE RESTRICT,
 name TEXT NOT NULL, level INTEGER NOT NULL CHECK(level BETWEEN 1 AND 3),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), UNIQUE(parent_id,name)
);
CREATE UNIQUE INDEX IF NOT EXISTS category_root_name ON product_categories(name) WHERE parent_id IS NULL;
CREATE INDEX IF NOT EXISTS documents_date_kind ON documents(date,kind,status);
CREATE INDEX IF NOT EXISTS documents_partner ON documents(partner_id,date);
CREATE INDEX IF NOT EXISTS documents_source_status_date ON documents(source_id,status,date);
CREATE INDEX IF NOT EXISTS payments_document_voided_date ON payments(document_id,voided,date);
CREATE INDEX IF NOT EXISTS lines_product ON document_lines(product_id,document_id);
CREATE INDEX IF NOT EXISTS lines_source ON document_lines(source_line_id);
CREATE INDEX IF NOT EXISTS stock_product_date ON stock_events(product_id,date,id);
CREATE INDEX IF NOT EXISTS audit_entity ON audit(entity,entity_id,id);
"""


def initialize(db):
    db.executescript(SCHEMA + SUPPLIER_SCHEMA + OFFLINE_SCHEMA + DIARY_SCHEMA + HOUSEHOLD_SCHEMA + EMAIL_SCHEMA+HEALTH_SCHEMA)
    columns = {row[1] for row in db.execute("PRAGMA table_info(products)")}
    if "retirement_target" not in columns:
        db.execute("ALTER TABLE products ADD COLUMN retirement_target INTEGER NOT NULL DEFAULT 0 CHECK(retirement_target IN (0,1))")
    category_columns = {row[1] for row in db.execute("PRAGMA table_info(product_categories)")}
    if "active" not in category_columns:
        db.execute("ALTER TABLE product_categories ADD COLUMN active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))")
    payment_columns = {row[1] for row in db.execute("PRAGMA table_info(payments)")}
    if "supplier_settlement_id" not in payment_columns:
        db.execute("ALTER TABLE payments ADD COLUMN supplier_settlement_id INTEGER REFERENCES supplier_settlements(id) ON DELETE RESTRICT")
    if "price_basis" not in {row[1] for row in db.execute("PRAGMA table_info(products)")}:
        db.execute("ALTER TABLE products ADD COLUMN price_basis INTEGER NOT NULL DEFAULT 1 CHECK(price_basis IN (1,100))")
    if "price_basis" not in {row[1] for row in db.execute("PRAGMA table_info(document_lines)")}:
        db.execute("ALTER TABLE document_lines ADD COLUMN price_basis INTEGER NOT NULL DEFAULT 1 CHECK(price_basis IN (1,100))")
    if "rounding_mode" not in {row[1] for row in db.execute("PRAGMA table_info(documents)")}:
        db.execute("ALTER TABLE documents ADD COLUMN rounding_mode TEXT NOT NULL DEFAULT 'won' CHECK(rounding_mode IN ('decimal','won'))")
