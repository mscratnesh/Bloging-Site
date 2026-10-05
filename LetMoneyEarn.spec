# -*- mode: python ; coding: utf-8 -*-


import glob, imageio_ffmpeg

# market reel: brand background, music, fonts and an ffmpeg binary, unpacked to market_reel_assets/
reel_assets = [(f, 'market_reel_assets') for f in glob.glob('market-reel/assets/*')]
reel_assets.append((imageio_ffmpeg.get_ffmpeg_exe(), 'market_reel_assets'))

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=reel_assets,
    hiddenimports=['openpyxl', 'xlrd'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # pandas' optional extras the server never uses; without this the one-file exe balloons past 350 MB
    excludes=['pyarrow', 'fsspec', 'matplotlib', 'scipy', 'sqlalchemy', 'torch', 'IPython'],
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
    name='LetMoneyEarn',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
