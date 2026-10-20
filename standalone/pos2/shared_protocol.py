"""Explicit LAN command contract. Private records and host administration stay local."""
from decimal import Decimal
from hashlib import sha256
import ipaddress
import json

SHARED_SCHEMA='''
CREATE TABLE IF NOT EXISTS shared_requests (
 request_id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 payload_hash TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL
);
'''

READS=frozenset('audit_log basic_records best_members calculation_policy cash_closes cash_expected categories commission_report count counts document documents form_sources gift_history gifts home_calendar inventory_close_detail inventory_closes ledger list_users lookup_barcode loyalty_products member_history member_prices member_view members next_member_code offline_report offline_report_filters online_preferences partners point_history price_schedules product_audit product_history products promotion promotions purchase_status quote report require_menu sales_form sales_forms settings stock_events supplier_group_members supplier_groups supplier_outstanding supplier_payment_history supplier_settlement_detail supplier_summary trade_members trade_partners trade_products trade_units units'.split())
WRITES=frozenset('add_payment adjust_points apply_count bulk_category bulk_update_products cancel_document cash_close clone_promotion create_count delete_category delete_count delete_draft delete_member delete_member_price delete_partner delete_price_schedule delete_product delete_promotion delete_sales_form delete_supplier_group delete_unit extend_promotion inventory_close post_document redeem_gift return_gift save_category save_draft save_gift save_member save_member_price save_partner save_price_schedule save_product save_promotion save_sales_form save_supplier_group save_unit set_supplier_group_members settle_supplier void_payment void_supplier_payment void_supplier_settlement'.split())
PRIVATE=frozenset('delete_desk_event delete_diary_entry delete_health_entry delete_household_entry delete_work_log desk_events diary_entries diary_exists diary_music_preferences due_desk_alerts health_entries household_memos household_report household_status lock_diary lock_household personal_theme popup_sound_enabled save_desk_event save_diary_entry save_diary_music_preferences save_health_entry save_household_entry save_household_memo save_personal_theme save_popup_sound_enabled save_work_log set_household_password setup_diary setup_household unlock_diary unlock_household change_diary_password work_logs'.split())
PRIVATE=PRIVATE|frozenset('household_accounts save_household_account household_transfers save_household_transfer delete_household_transfer household_vehicles save_household_vehicle household_fixed_costs save_household_fixed_cost apply_household_fixed_costs household_dashboard household_vehicle_history'.split())
PRIVATE=PRIVATE|frozenset('household_vehicle_logs save_household_vehicle_log delete_household_vehicle_log personal_attachments add_personal_attachment personal_attachment_data delete_personal_attachment inspiration'.split())
PRIVATE=PRIVATE|frozenset('save_household_budget household_budget due_household_fixed_alerts'.split())
PRIVATE=PRIVATE|{'household_spending_comparison'}
PRIVATE=PRIVATE|frozenset('household_category_rules save_household_category_rule suggest_household_category'.split())
PRIVATE=PRIVATE|{'health_report'}
READS=READS|{'stock_adjustments','inventory_assets','inventory_asset_comparison'}
READS=READS|{'sales_period_comparison'}
READS=READS|{'sales_history'}
WRITES=WRITES|{'post_stock_adjustment'}
PRIVATE=PRIVATE|{'due_health_alerts'}
PRIVATE=PRIVATE|frozenset('household_vehicle_report household_vehicle_obligations save_household_vehicle_obligation complete_household_vehicle_obligation void_household_vehicle_obligation due_household_vehicle_alerts'.split())
PRIVATE=PRIVATE|frozenset('household_plans save_household_plan delete_household_plan household_annual_report household_financial_overview household_cash_forecast'.split())
PRIVATE=PRIVATE|{'split_household_entry','household_custom_report'}
PRIVATE=PRIVATE|{'work_log_detail','work_log_report','work_log_files','add_work_log_file','work_log_file_data','delete_work_log_file'}


READS=READS|frozenset({'inventory_status'})

def encode(value):
    def default(item):
        if isinstance(item,Decimal):return {'$decimal':str(item)}
        raise TypeError('공유할 수 없는 자료 형식입니다.')
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False,default=default)


def decode(value):
    def hook(item):
        if set(item)=={'$decimal'}:
            result=Decimal(item['$decimal'])
            if not result.is_finite():raise ValueError('유한한 금액만 허용됩니다.')
            return result
        return item
    return json.loads(value,object_hook=hook,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('잘못된 숫자입니다.')))


def private_address(value,allow_loopback=False):
    try:address=ipaddress.IPv4Address(value)
    except (ValueError,TypeError):raise ValueError('기준 PC의 숫자 IPv4 주소를 입력하세요.') from None
    if address.is_loopback and allow_loopback:return str(address)
    ranges=(ipaddress.IPv4Network('10.0.0.0/8'),ipaddress.IPv4Network('172.16.0.0/12'),ipaddress.IPv4Network('192.168.0.0/16'))
    if not any(address in network for network in ranges):
        raise ValueError('같은 내부 네트워크의 사설 IPv4 주소만 사용할 수 있습니다.')
    return str(address)


def fingerprint(value):return sha256(encode(value).encode()).hexdigest()


def client_actor(actor):
    """Host-only users/settings/restore controls must not appear on a client."""
    result=dict(actor)
    result['host_admin']=actor['role']=='admin'
    if result['role']=='admin':result['role']='staff'
    result['permissions']=[p for p in actor['permissions'] if p!='admin']
    return result
