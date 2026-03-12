from setuptools import setup

APP     = ["app.py"]
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "LSUIElement":                True,   # No Dock icon — menu bar only
        "CFBundleName":               "Realtime Upload & Download",
        "CFBundleDisplayName":        "Realtime Upload & Download",
        "CFBundleIdentifier":         "com.realtime.uploaddownload",
        "CFBundleVersion":            "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable":    True,
        "NSAccessibilityUsageDescription": "Required to enable the global keyboard shortcut (⌘⇧D) for cycling display modes.",
    },
    "packages": ["rumps", "psutil", "pynput"],
}

setup(
    app=APP,
    name="Realtime Upload & Download",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
