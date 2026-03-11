# Realtime Upload & Download

A lightweight macOS menu bar app that displays real-time upload and download speeds and logs your total bandwidth usage over time.

---

## Features

- **Live speed display** in KB/s or Mbps, updated every 2 seconds (configurable)
- **Smooth rolling average** to eliminate jitter
- **Session stats** — total uploaded/downloaded and peak speeds since launch
- **Bandwidth logging** — automatic CSV log with configurable retention (1–30 days, default 7)
- **Total bandwidth view** — see how much data you've consumed over the retention window
- **Interface selection** — auto-detect your active NIC or manually choose one
- **Display modes** — Speed Only, Totals Only, or Speed + Totals in the menu bar title
- **Sleep-aware** — correctly handles Mac sleep/wake cycles (no false spikes on resume)
- **Launch at login** — optional auto-start via LaunchAgent
- **Export & clear logs** directly from the menu

---

## Installation

### What to expect (unsigned app)

This app is distributed **unsigned**. macOS Gatekeeper will warn you the first time you try to open it:

> *"Realtime Upload & Download" cannot be opened because the developer cannot be verified.*

This is normal for open-source utilities not distributed through the Mac App Store. Follow the steps below to open it — you only need to do this **once**.

---

### Step 1 — Download

Go to the [Releases](../../releases) page and download the latest `RealtimeUploadDownload.dmg`.

---

### Step 2 — Open the DMG

Double-click `RealtimeUploadDownload.dmg`. In the window that opens, drag **Realtime Upload & Download** into the **Applications** folder shortcut.

---

### Step 3 — First launch (bypass Gatekeeper)

Choose **one** of the following methods:

#### Method A — Right-click to open (recommended)
1. Open **Finder** and navigate to your **Applications** folder
2. **Right-click** (or Control-click) on `Realtime Upload & Download`
3. Select **Open** from the context menu
4. Click **Open** in the dialog that appears

#### Method B — System Settings
1. Try to open the app normally — macOS will block it and show an error
2. Open **System Settings → Privacy & Security**
3. Scroll down to the security section near the bottom
4. Click **Open Anyway** next to the message about Realtime Upload & Download
5. Confirm by clicking **Open** in the dialog

After the first successful launch, the app will open normally from that point on.

---

### Step 4 — Allow at startup (optional)

Once running, click the menu bar title and enable **Launch at Login** to have the app start automatically every time you log in.

---

## Usage

Once running, the app appears in your menu bar. Click the title to open the menu.

### Menu bar title

| Display Mode | Example |
|---|---|
| Speed Only (default) | `↑1.2 ↓4.8 Mbps` |
| Totals Only | `↑ 120.0 MB  ↓ 450.0 MB` |
| Speed + Totals | `↑1.2 ↓4.8 Mbps  ↑ 120.0 MB ↓ 450.0 MB` |

### Menu reference

| Item | Description |
|---|---|
| **Session** | Total data sent/received since the app was last launched |
| **Peak** | Highest recorded speed this session |
| **View Total Bandwidth…** | Dialog showing total data used within the log retention window |
| **Display Mode** | What appears in the menu bar title |
| **Units** | Toggle between Mbps and KB/s |
| **Update Interval** | How often the display refreshes (0.5s, 1s, 2s, 5s, 10s) |
| **Interface** | Auto-detect or manually select a network interface |
| **Log Settings** | Configure retention period, open/export/clear the log file |
| **Launch at Login** | Toggle auto-start on login |
| **Quit** | Gracefully quits and flushes any pending log data |

> **Note on update interval:** Faster intervals (0.5s, 1s) provide more responsive readings but use slightly more CPU and battery.

---

## Log file

Bandwidth data is logged to:

```
~/Library/Logs/RealtimeUploadDownload/bandwidth.csv
```

You can open this directly via **Log Settings → Open Log File**, or export a dated copy to your Desktop via **Log Settings → Export Log…**.

### Log format

| Column | Description |
|---|---|
| `timestamp` | ISO 8601 timestamp (e.g. `2026-03-11T10:00:00`) |
| `interface` | Network interface name (e.g. `en0`) |
| `bytes_sent` | Bytes uploaded during this interval |
| `bytes_recv` | Bytes downloaded during this interval |
| `duration_seconds` | Length of the interval in seconds |

Entries are written approximately every 60 seconds. Old entries are automatically trimmed to stay within your configured retention window. The default retention is **7 days**, configurable between 1 and 30 days under **Log Settings → Log Retention**.

---

## Uninstalling

1. Quit the app from the menu bar (**Quit**)
2. Delete the app from **Applications**
3. Optionally remove all app data:

```bash
rm -rf ~/Library/Application\ Support/RealtimeUploadDownload
rm -rf ~/Library/Logs/RealtimeUploadDownload
rm -f ~/Library/LaunchAgents/com.realtime.uploaddownload.plist
```

---

## Building from source

### Requirements

- macOS 12 or later
- Python 3.10 or later
- [Homebrew](https://brew.sh) (for `create-dmg`)

### Steps

```bash
# Clone the repo
git clone https://github.com/yourusername/realtime-upload-download.git
cd realtime-upload-download

# Install create-dmg (only needed for DMG packaging)
brew install create-dmg

# Build the .app bundle and DMG
chmod +x build.sh
./build.sh
```

The distributable DMG will be at `dist/RealtimeUploadDownload.dmg`.

### Run directly without building

```bash
pip install rumps psutil
python3 app.py
```

---

## License

MIT
