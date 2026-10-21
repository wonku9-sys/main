# Claude optimization review — 2026-10-21 (Korea)

Input: SY-POS-v2.4.0rc22-source-클로드 최적화.zip.
The uploaded source was extracted separately; the original workspace and all
real business/personal data were preserved. No source was published externally.

## Confirmed fixes

1. Catalog cache previously ignored stock movements. Purchases, sales, returns,
   cancellation and inventory counts can change product stock/edit tokens without
   a product audit entry. The revision now includes stock_events MAX(id).
2. Shared-PC protocol did not expose catalog_revision; opening optimized catalog
   or trade entry on a client could fail. Added it to the read-only allowlist.
3. ProductPicker seeded its cache with catalog_revision but compared audit_revision
   on subsequent reads, discarding the optimization. Both now match for default
   catalog loads; custom loaders retain the general audit revision.
4. The shared window cache now rechecks authority, separates actors, and records
   its new revision only after a successful read, so a temporary read failure
   cannot leave an old list falsely marked current.
5. requirements.txt omitted cryptography, xlrd and korean-lunar-calendar despite
   pyproject.toml requiring them. Plain requirements installs could fail at startup
   or fail on XLS import. Both runtime dependency lists now agree.

## Validation

- FINAL corrected-source full suite with permitted loopback: **832 passed,
  1 skipped in 288.40 seconds**. No remaining test failures.
- Uploaded ZIP CRC: passed (260 entries).
- Full Linux/Qt offscreen suite: 809 passed, 1 skipped. Eighteen socket-related
  failures/errors were caused by the restricted test sandbox; those suites are
  rerun separately with permitted loopback networking (see delivery test logs).
- Loopback reruns: shared-PC TLS/network suite 24 passed; customer registration,
  credit limits and address bridge suite 13 passed.
- New regression + catalog performance + purchasing workspace: 19 passed.
- Application smoke: 73 desktop pages and actual synthetic transaction, return,
  persistence, backup/restore and protected-reset workflows passed.
- Clean source startup reached the login dialog; cancelling returned normally.
- Windows package checks: all manifest file hashes, launcher entry point,
  required libraries, Python syntax and x64 PE headers passed. Static dependency
  inspection covered 172 modules; unused Qt PostgreSQL/Mimer plugins require
  optional database-client DLLs not used by this SQLite application.
- Runtime data and source ZIPs exclude actual business databases and credentials.

## Windows bundle — important limit

assemble_windows.py packages the verified CPython 3.12.10 x64 runtime and official
PySide6 6.8.3 Windows libraries with the corrected source and additional Windows
wheels. A relocatable distlib launcher starts pos2.app, not the old application.
Wheel RECORD hashes, ZIP CRC and PE x64 architecture are checked. File checksums
are recorded in BUNDLE-MANIFEST.json. No Python installation is required.

This is a Windows-runtime assembly performed on Linux, **not a native Windows
PyInstaller build or native Windows execution test**. No Wine/Windows environment
is available here. Windows startup, compositor animations, physical printers,
DT-970 hardware, card approval and bank transfer are not verified. Manual card
recording is not card approval. The EXE is unsigned; Windows may show publisher or
SmartScreen warnings. Do not disable Windows security settings.

Extract the complete ZIP to a new folder and launch SY-POS.exe. Do not overwrite
an existing installation. The app retains its existing LOCALAPPDATA data location;
existing records may be loaded if present. Back up real data before first use.
For shared-PC use, install the same reviewed version on the host and all clients.
