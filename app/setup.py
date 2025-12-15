"""
py2app build configuration for Phocus Monitor Launcher

This creates a lightweight launcher app that:
- Provides a GUI for selecting output directory and duration
- Finds and runs the phocus-monitor script from its venv
- Guides users through setup if the venv isn't found

To build the app:
    cd app
    python setup.py py2app

The resulting .app will be in app/dist/
"""

from setuptools import setup

APP = ['launcher.py']

OPTIONS = {
    'argv_emulation': False,
    'plist': {
        'CFBundleName': 'Phocus Monitor',
        'CFBundleDisplayName': 'Phocus Monitor',
        'CFBundleIdentifier': 'com.tonalphoto.phocusmonitor',
        'CFBundleVersion': '2.5.1',
        'CFBundleShortVersionString': '2.5.1',
        'NSHumanReadableCopyright': '© 2025 Konrad Michels',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',  # Big Sur minimum for Apple Silicon
        'NSAppleEventsUsageDescription': 'Phocus Monitor needs to run AppleScript for admin privileges and dialogs.',
    },
    # Minimal includes - launcher only uses stdlib
    'includes': [
        'subprocess',
    ],
    'excludes': [
        'tkinter',
        'test',
        'unittest',
        'psutil',      # Not needed in launcher
        'matplotlib',  # Not needed in launcher
        'numpy',       # Not needed in launcher
        'PIL',
    ],
}

setup(
    name='Phocus Monitor',
    app=APP,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
