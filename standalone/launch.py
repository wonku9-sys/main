"""Independent entry point, with file logging only in isolated smoke mode."""
import os
import sys

if __name__ == "__main__":
    smoke = '--smoke-test' in sys.argv
    if smoke and os.environ.get('SY_POS_SMOKE_LOG'):
        from pathlib import Path
        import faulthandler
        log = Path(os.environ['SY_POS_SMOKE_LOG'])
        log.parent.mkdir(parents=True, exist_ok=True)
        stream = log.open('w', encoding='utf-8', buffering=1)
        sys.stdout = sys.stderr = stream
        faulthandler.enable(file=stream)
        faulthandler.dump_traceback_later(60, repeat=True, file=stream)
        print('SMOKE_ENTRY_STARTED', flush=True)
    try:
        from pos2.app import main
        if smoke:print('SMOKE_IMPORT_COMPLETE', flush=True)
        raise SystemExit(main())
    except Exception:
        if not smoke:raise
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
