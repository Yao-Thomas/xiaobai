# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['xb_chat.py'],
    pathex=[],
    binaries=[],
    datas=[('xb_pcsr.ps1', '.'), ('xb_pcsr_async.ps1', '.')],
    hiddenimports=['xb_client', 'xb_audio', 'xb_pcsr'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'matplotlib', 'PIL'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='系统管家小白',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='系统管家小白',
)
