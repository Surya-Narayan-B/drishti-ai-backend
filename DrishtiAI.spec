# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import collect_data_files

# Find the pyttsx3 drivers path dynamically
import pyttsx3.drivers
pyttsx3_drivers_path = pyttsx3.drivers.__path__[0]

a = Analysis(
    ['real_time_eye_tracking.py'],
    pathex=[],
    binaries=[],
    # Add all your data files and folders here
    datas=[
        ('wellness_assistant.py', '.'),
        ('calibration_profile.json', '.'),
        ('monitoring_data.db', '.'),
        ('templates', 'templates'),
        ('static', 'static'),
        (pyttsx3_drivers_path, 'pyttsx3/drivers') # Dynamically add the drivers
    ],
    # Add your hidden imports here
    hiddenimports=['webbrowser', 'pyttsx3.drivers.sapi5'],
    # Point to your hooks folder
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='DrishtiAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False, # This is the same as --windowed
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)