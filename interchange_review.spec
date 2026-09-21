# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["launcher.py"],
    pathex=["src"],
    binaries=[],
    datas=[("assets", "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# 번들 런타임의 제3자 API-set/ICU DLL은 Qt보다 먼저 수집될 수 있다.
# 이를 제외하고 Windows 시스템 DLL을 사용해야 QtCore가 정상 기동한다.
a.binaries = type(a.binaries)(
    item for item in a.binaries
    if not item[0].lower().startswith(("api-ms-win-", "ext-ms-win-", "icu"))
    and item[0].lower() != "ucrtbase.dll"
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="K-GSS_v3.7.0",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/interchange.ico"],
)
