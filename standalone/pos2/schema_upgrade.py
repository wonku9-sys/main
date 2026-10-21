"""Atomic, backed-up upgrades of known stock and manual-payment constraints."""
import re
import secrets
from datetime import datetime


def upgrade_business_schema(store):
    if not store._opening_version or store._opening_version>=215:return
    from .schema import SCHEMA
    from .operations import OPERATIONS_SCHEMA
    from .offline_features import OFFLINE_SCHEMA
    db=store.db
    definitions=SCHEMA+OPERATIONS_SCHEMA+OFFLINE_SCHEMA
    names=('payments','supplier_settlements') if store._opening_version>=212 else ('products','stock_events','inventory_count_lines','inventory_closes','inventory_close_lines','sales_forms','payments','supplier_settlements')
    replacements=[]
    for name in names:
        row=db.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?',(name,)).fetchone()
        if row is None:continue
        statement=re.search(r'CREATE TABLE IF NOT EXISTS '+name+r' \([\s\S]*?\n\);',definitions).group()
        # Some legacy-version fixtures already have current constraints.
        normalize=lambda value:''.join(value.split()).replace('IFNOTEXISTS','').rstrip(';')
        if normalize(row[0])!=normalize(statement):replacements.append((name,statement))
    if not replacements:return
    if store.path and not getattr(store,'migration_backup_path',None):
        target=store._backup_directory()/f'업데이트전-자동백업_{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(4)}.db'
        store._backup_file(target);store.migration_backup_path=str(target)
    foreign=db.execute('PRAGMA foreign_keys').fetchone()[0]
    legacy=db.execute('PRAGMA legacy_alter_table').fetchone()[0]
    db.execute('PRAGMA foreign_keys=OFF');db.execute('PRAGMA legacy_alter_table=ON')
    db.execute('BEGIN IMMEDIATE')
    try:
        objects=[row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE type IN ('index','trigger') AND sql IS NOT NULL")]
        for name,statement in replacements:
            columns=[row[1] for row in db.execute(f'PRAGMA table_info({name})')]
            column_sql=','.join('"'+column+'"' for column in columns)
            old='_sy_upgrade_'+name
            db.execute(f'ALTER TABLE "{name}" RENAME TO "{old}"')
            db.execute(statement)
            db.execute(f'INSERT INTO "{name}" ({column_sql}) SELECT {column_sql} FROM "{old}"')
            db.execute(f'DROP TABLE "{old}"')
        for statement in objects:
            # Recreate only objects removed with the old tables.
            db.execute(statement.replace('CREATE UNIQUE INDEX ','CREATE UNIQUE INDEX IF NOT EXISTS ',1)
                       .replace('CREATE INDEX ','CREATE INDEX IF NOT EXISTS ',1)
                       .replace('CREATE TRIGGER ','CREATE TRIGGER IF NOT EXISTS ',1)
                       .replace('IF NOT EXISTS IF NOT EXISTS','IF NOT EXISTS'))
        if db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('업데이트 자료 연결 검증에 실패했습니다. 보호 백업은 유지됩니다.')
        db.commit()
    except BaseException:
        db.rollback();raise
    finally:
        db.execute(f'PRAGMA legacy_alter_table={legacy}');db.execute(f'PRAGMA foreign_keys={foreign}')
