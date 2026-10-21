"""RAM-only private unlock retention for one authenticated application session."""

def local_store(store):
    return store.private if getattr(store,"is_shared_client",False) else store


def forget_key(store,kind):
    key=getattr(store,"_private_session_keys",{}).pop(kind,None)
    if key is not None:key[:]=bytes(len(key))


def _validate(store,kind,key):
    if kind=="diary":store._diary_require_key(key)
    elif kind=="household":store._require_household_key(key)
    else:raise ValueError("개인 기록 구분을 확인하세요.")


def remember_key(store,kind,key):
    store=local_store(store);_validate(store,kind,key);forget_key(store,kind)
    if not hasattr(store,"_private_session_keys"):store._private_session_keys={}
    store._private_session_keys[kind]=bytearray(key)


def cached_key(store,kind):
    store=local_store(store);key=getattr(store,"_private_session_keys",{}).get(kind)
    if key is None:return None
    try:_validate(store,kind,key)
    except (ValueError,PermissionError):forget_key(store,kind);return None
    return bytearray(key)
