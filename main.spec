# -*- mode: python ; coding: utf-8 -*-

import os

block_cipher = None

# Keep only the Qt binaries the app actually needs (QtCore/Gui/Widgets).
# PyInstaller's PySide6 hook otherwise bundles the entire Qt distribution
# (WebEngine 205MB, Qml, Quick, Pdf, Designer, ...).
def _keep_qt(src, dst):
    name = os.path.basename(src).lower()
    if 'pyside6' not in src.replace('\\', '/').lower() and 'shiboken' not in src.lower():
        return True
    keep = {
        'qt6core.dll', 'qt6gui.dll', 'qt6widgets.dll',
        'qtcore.pyd', 'qtgui.pyd', 'qtwidgets.pyd',
        'pyside6.abi3.dll', 'shiboken6.abi3.dll', 'shiboken6.abi3.pyd',
        'shiboken.pyd', 'shiboken.abi3.pyd',
        'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'msvcp140_atomic_wait.dll',
        'vcruntime140.dll', 'vcruntime140_1.dll',
        'concrt140.dll', 'vcomp140.dll', 'vcamp140.dll', 'vccorlib140.dll',
        'qwindows.dll', 'qmodernwindowsstyle.dll',
        'qico.dll', 'qjpeg.dll', 'qgif.dll', 'qwebp.dll',
        'qsvg.dll', 'qsvgicon.dll', 'qt6svg.dll',
    }
    # keep the windows platform plugin + minimal imageformats/styles
    if '/plugins/platforms/qwindows.dll' in src.replace('\\', '/').lower():
        return True
    if '/plugins/styles/qmodernwindowsstyle.dll' in src.replace('\\', '/').lower():
        return True
    if '/plugins/imageformats/' in src.replace('\\', '/').lower():
        name = os.path.basename(src).lower()
        return name in {'qico.dll', 'qjpeg.dll', 'qgif.dll', 'qwebp.dll', 'qsvg.dll'}
    if '/plugins/iconengines/qsvgicon.dll' in src.replace('\\', '/').lower():
        return True
    return name in keep

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config.json', '.'),
        ('credentials.json', '.'),
        ('icons/app_icon.ico', 'icons'),
        ('icons/app_icon.png', 'icons'),
    ],
    hiddenimports=[
        'loguru',
        'watchdog',
        'watchdog.observers',
        'googleapiclient',
        'googleapiclient.http',
        'google_auth_httplib2',
        'httplib2',
        'google_auth_oauthlib',
        'google.oauth2.credentials',
        'PySide6',
        'sqlite3',
        'winreg'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        # Qt modules the app never uses (Qt6WebEngineCore alone is 205MB)
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineQuick',
        'PySide6.QtWebChannel',
        'PySide6.QtQml',
        'PySide6.QtQmlModels',
        'PySide6.QtQuick',
        'PySide6.QtQuickControls2',
        'PySide6.QtQuickWidgets',
        'PySide6.QtQuick3D',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtDesigner',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtNetwork',
        'PySide6.QtNetworkAuth',
        'PySide6.QtSvg',
        'PySide6.QtSvgWidgets',
        'PySide6.QtSql',
        'PySide6.QtTest',
        'PySide6.QtXml',
        'PySide6.QtXmlPatterns',
        'PySide6.QtUiTools',
        'PySide6.QtHelp',
        'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets',
        'PySide6.QtPrintSupport',
        'PySide6.QtConcurrent',
        'PySide6.QtDBus',
        'PySide6.QtBluetooth',
        'PySide6.QtNfc',
        'PySide6.QtPositioning',
        'PySide6.QtSensors',
        'PySide6.QtSerialPort',
        'PySide6.QtWebSockets',
        'PySide6.QtWebView',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtGraphs',
        'PySide6.QtRemoteObjects',
        'PySide6.QtScxml',
        'PySide6.QtStateMachine',
        'PySide6.QtTextToSpeech',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DRender',
        'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic',
        'PySide6.Qt3DAnimation',
        'PySide6.Qt3DExtras',
        'PySide6.QtQmlCompiler',
        'PySide6.QtVirtualKeyboard',
        'PySide6.QtWaylandClient',
        'PySide6.QtWebEngineCore',
        'PySide6.QtAndroidExtras',
        'PySide6.QtMacExtras',
        'PySide6.QtWinExtras',
        'PySide6.QtX11Extras',
        'PySide6.QtAxContainer',
        'PySide6.QtOpcUa',
        'PySide6.QtQuickTimeline',
        'PySide6.QtQuickParticles',
        'PySide6.QtShaderTools',
        'PySide6.QtMultimediaQuick',
        'PySide6.QtWebSockets',
        'PySide6.QtLabsAnimation',
        'PySide6.QtLabsFolderListModel',
        'PySide6.QtLabsQmlModels',
        'PySide6.QtLabsSettings',
        'PySide6.QtLabsSharedImage',
        'PySide6.QtLabsWavefrontMesh',
        'PySide6.QtQmlCore',
        'PySide6.QtQmlModels',
        'PySide6.QtQuickLayouts',
        'PySide6.QtQuickShapes',
        'PySide6.QtQuickTemplates2',
        'PySide6.QtQuickWidgets',
        'PySide6.QtQmlWorkScript',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Filter out the bulk of Qt that the PySide6 hook auto-collects.
a.binaries = [b for b in a.binaries if _keep_qt(b[0], b[1])]

# Also drop unneeded data files (translations, resources, extra plugins).
# Keep googleapiclient's cached discovery document for the Drive API only
# (~198KB). Without it, build('drive','v3') raises UnknownApiNameOrVersion
# ('name: drive version: v3') because static_discovery defaults to True and the
# app runs offline-first; the full discovery cache is ~30MB and unnecessary.
def _keep_qt_data(src, dst):
    s = src.replace('\\', '/').lower()
    # googleapiclient discovery documents: keep ONLY drive.v3.json
    if '/discovery_cache/documents/' in s:
        return s.endswith('/drive.v3.json')
    if 'pyside6' not in src.replace('\\', '/').lower():
        return True
    # keep only the platform plugin we need
    if '/plugins/platforms/' in s:
        return s.endswith('/qwindows.dll')
    if '/plugins/' in s:
        n = os.path.basename(src).lower()
        keep = {'qico.dll', 'qjpeg.dll', 'qgif.dll', 'qwebp.dll', 'qsvg.dll',
                'qsvgicon.dll', 'qmodernwindowsstyle.dll'}
        return n in keep
    # drop translations / qt.conf variants not needed
    if '/translations/' in s:
        return False
    if '/qml/' in s or '/qmltooling/' in s:
        return False
    return True

a.datas = [d for d in a.datas if _keep_qt_data(d[0], d[1])]


pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ZaloPCSyncDrive',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI mode (no command window popup)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icons/app_icon.ico' if os.path.exists('icons/app_icon.ico') else None,
    version='version_info.txt'
)
