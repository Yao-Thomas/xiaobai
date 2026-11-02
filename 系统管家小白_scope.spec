# -*- mode: python ; coding: utf-8 -*-
# 系统管家小白 · 打包配置（含协同示波器 scope_panel）
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = [
    'numpy',
    'scope_panel',      # ★ 新增：协同示波器面板
    'xb_audio',
    'xb_client',
    'xb_pcsr',
]
tmp_ret = collect_all('sounddevice')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

a = Analysis(
    ['D:/ubuntu_iso/xb_chat.py'],
    pathex=['D:/ubuntu_iso'],      # ★ 让 PyInstaller 能找到 scope_panel.py
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='系统管家小白',
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
    icon=None,
)
