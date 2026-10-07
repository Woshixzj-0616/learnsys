# -*- mode: python ; coding: utf-8 -*-
"""把「问一问」打包成一个真正的 Windows 程序。

用法：项目根目录下双击 `打包.cmd`（或者 `.venv\\Scripts\\python.exe -m PyInstaller 问一问.spec`）。
产物：`dist\\问一问\\问一问.exe`（整个 `dist\\问一问\\` 文件夹一起拷走就能用）。
"""
import os
import sys

SPECPATH_ROOT = SPECPATH
sys.path.insert(0, SPECPATH_ROOT)

# 版本号**只写一处**：learnsys/ask/__init__.py 的 VERSION。
# 这里把它变成 exe 的版本资源（任务管理器 / 文件属性里看到的那个），不用再手改 版本信息.txt。
from learnsys.ask import VERSION  # noqa: E402
from PyInstaller.utils.win32.versioninfo import (  # noqa: E402
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

_parts = [int(p) for p in VERSION.split(".")]
_parts = (_parts + [0, 0, 0, 0])[:4]
_vstr = ".".join(str(p) for p in _parts)

version = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=_parts,
        prodvers=_parts,
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo([
            StringTable("080404b0", [
                StringStruct("CompanyName", "学习系统"),
                StringStruct("FileDescription", "问一问"),
                StringStruct("FileVersion", _vstr),
                StringStruct("InternalName", "问一问"),
                StringStruct("LegalCopyright", "MIT License"),
                StringStruct("OriginalFilename", "问一问.exe"),
                StringStruct("ProductName", "问一问"),
                StringStruct("ProductVersion", _vstr),
            ])
        ]),
        VarFileInfo([VarStruct("Translation", [2052, 1200])]),
    ],
)

a = Analysis(
    [os.path.join(SPECPATH, '问一问.py')],
    pathex=[SPECPATH],
    binaries=[],
    datas=[],
    hiddenimports=[
        # comtypes 是「用到才现生成」的，PyInstaller 扫不到 —— 得手点名
        'comtypes',
        'comtypes.client',
        'comtypes.shelllink',
        'comtypes.persist',
        'comtypes.stream',
        'comtypes.typeinfo',
        'comtypes.automation',
        'comtypes.gen',
        # 录制那三路（声音转写 / 回环采集 / 快照）的依赖 —— 都是懒加载，得手点名
        'faster_whisper',
        'ctranslate2',
        'onnxruntime',
        'tokenizers',
        'av',
        'numpy',
        'pyaudiowpatch',
        'pycaw',
        'pycaw.pycaw',
        'pycaw.utils',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 「问一问」不碰这些：剔掉，免得白白胖几百兆
        # （⚠️ numpy / faster_whisper / ctranslate2 / onnxruntime 不能剔 —— 录制的声音转写要用）
        'tkinter',
        'scipy',
        'pandas',
        'torch',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuick3D',
        'PySide6.QtQuickWidgets',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineQuick',
        'PySide6.QtWebChannel',
        'PySide6.QtWebSockets',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtGraphs',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DRender',
        'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic',
        'PySide6.Qt3DAnimation',
        'PySide6.Qt3DExtras',
        'PySide6.QtSql',
        'PySide6.QtTest',
        'PySide6.QtHelp',
        'PySide6.QtDesigner',
        'PySide6.QtUiTools',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtBluetooth',
        'PySide6.QtNfc',
        'PySide6.QtPositioning',
        'PySide6.QtSerialPort',
        'PySide6.QtRemoteObjects',
        'PySide6.QtSensors',
        'PySide6.QtSpatialAudio',
        'PySide6.QtTextToSpeech',
        'PySide6.QtScxml',
        'PySide6.QtStateMachine',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='问一问',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                       # 双击不弹黑框
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SPECPATH, '问一问.ico'),
    version=version,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='问一问',
)
