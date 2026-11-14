# ChatBridge 2.60.0 — build on Windows x64 only.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH)
datas = [
    *[(str(path), 'desktop/ui') for path in (root / 'desktop' / 'ui').glob('*') if path.is_file()],
    *[(str(path), 'desktop/translations') for path in (root / 'desktop' / 'translations').glob('*') if path.is_file()],
    (str(root / 'desktop' / 'agent_cb.js'), 'desktop'),
    (str(root / 'shared'), 'shared'),
    (str(root / 'icon.ico'), '.'),
]
binaries = []
hiddenimports = ['webview.platforms.edgechromium', 'webview.platforms.winforms',
                 'clr', 'pythonnet', 'desktop.app', 'websockets.legacy.server',
                 'websockets.legacy.client']
for package in ('webview', 'pythonnet'):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules('desktop')
a = Analysis([str(root / 'desktop' / 'app.py')], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             hookspath=[], runtime_hooks=[], excludes=['PyQt5','PyQt6','PySide2','PySide6','tkinter'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, name='ChatBridge-2.60.0',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, icon=str(root / 'icon.ico'))
