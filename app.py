#!/usr/bin/env python3
"""Realtime Upload & Download — macOS menu bar network speed monitor"""

import csv
import datetime
import json
import os
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import psutil
import rumps

# ── Constants ─────────────────────────────────────────────────────────────────

APP_NAME    = "Realtime Upload & Download"
APP_VERSION = "1.0.0"
BUNDLE_ID   = "com.realtime.uploaddownload"

CONFIG_DIR  = Path.home() / "Library" / "Application Support" / "RealtimeUploadDownload"
LOG_DIR     = Path.home() / "Library" / "Logs" / "RealtimeUploadDownload"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE    = LOG_DIR / "bandwidth.csv"
LOCK_FILE   = Path("/tmp") / "RealtimeUploadDownload.lock"
PLIST_PATH  = Path.home() / "Library" / "LaunchAgents" / f"{BUNDLE_ID}.plist"

LOG_FLUSH_INTERVAL = 60  # seconds between CSV writes

DEFAULT_CONFIG = {
    "unit":                    "mbps",  # "mbps" | "kbps"
    "update_interval":         2.0,     # seconds
    "interface":               "auto",  # "auto" | NIC name
    "display_mode":            "speed", # "speed" | "totals" | "both"
    "log_retention_days":      7,
    "rolling_average_samples": 3,
}

INTERVALS = {
    "0.5s":          0.5,
    "1s":            1.0,
    "2s (default)":  2.0,
    "5s":            5.0,
    "10s":           10.0,
}

RETENTION_OPTIONS = [1, 3, 7, 14, 30]


# ── Single-instance lock ───────────────────────────────────────────────────────

def acquire_lock():
    import fcntl
    fd = open(str(LOCK_FILE), "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd.write(str(os.getpid()))
        fd.flush()
        return fd
    except IOError:
        subprocess.run(
            ["osascript", "-e",
             f'display alert "{APP_NAME}" message "The app is already running."'],
            capture_output=True,
        )
        sys.exit(1)


# ── Formatting helpers ────────────────────────────────────────────────────────

def format_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def format_speed(bps: float, unit: str) -> str:
    if unit == "mbps":
        return f"{bps * 8 / 1_000_000:.1f} Mbps"
    return f"{bps / 1024:.1f} KB/s"


def format_speed_short(bps: float, unit: str) -> str:
    if unit == "mbps":
        return f"{bps * 8 / 1_000_000:.1f}"
    return f"{bps / 1024:.0f}"


def unit_label(unit: str) -> str:
    return "Mbps" if unit == "mbps" else "KB/s"


def get_default_interface() -> str | None:
    try:
        out = subprocess.run(
            ["route", "get", "default"],
            capture_output=True, text=True, timeout=2,
        ).stdout
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("interface:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    # Fallback: first non-loopback NIC with traffic
    try:
        for nic in psutil.net_io_counters(pernic=True):
            if not nic.startswith("lo"):
                return nic
    except Exception:
        pass
    return None


# ── App ───────────────────────────────────────────────────────────────────────

class RealtimeUploadDownload(rumps.App):

    def __init__(self, lock_fd):
        self._lock_fd = lock_fd

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        self.config = self._load_config()

        # Network state
        self._last_counters = None
        self._last_time     = None
        self._active_iface  = None

        # Rolling average
        n = self.config["rolling_average_samples"]
        self._up_samples = deque(maxlen=n)
        self._dn_samples = deque(maxlen=n)

        # Session totals & peaks
        self._session_sent = 0
        self._session_recv = 0
        self._peak_up      = 0.0
        self._peak_dn      = 0.0

        # Log accumulator (flushed every LOG_FLUSH_INTERVAL seconds)
        self._acc_sent   = 0
        self._acc_recv   = 0
        self._acc_start  = time.time()
        self._last_flush = time.time()

        super().__init__(APP_NAME, title="↑-- ↓--", quit_button=None)

        self._init_log()
        self._build_menu()
        self._trim_log()

        self._timer = rumps.Timer(self._tick, self.config["update_interval"])
        self._timer.start()

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    loaded = json.load(f)
                merged = {**DEFAULT_CONFIG, **loaded}
                merged["update_interval"] = float(merged["update_interval"])
                return merged
            except Exception:
                pass
        return DEFAULT_CONFIG.copy()

    def _save_config(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config, f, indent=2)

    # ── Log ───────────────────────────────────────────────────────────────────

    def _init_log(self):
        if not LOG_FILE.exists():
            with open(LOG_FILE, "w", newline="") as f:
                csv.writer(f).writerow(
                    ["timestamp", "interface", "bytes_sent", "bytes_recv", "duration_seconds"]
                )

    def _flush_log(self, marker: str = None):
        now      = datetime.datetime.now().isoformat(timespec="seconds")
        duration = round(time.time() - self._acc_start, 1)
        iface    = self._active_iface or "unknown"

        row = (
            [now, f"[{marker}]", 0, 0, 0]
            if marker
            else [now, iface, self._acc_sent, self._acc_recv, duration]
        )

        with open(LOG_FILE, "a", newline="") as f:
            csv.writer(f).writerow(row)

        self._acc_sent  = 0
        self._acc_recv  = 0
        self._acc_start = time.time()

    def _trim_log(self):
        if not LOG_FILE.exists():
            return
        cutoff = datetime.datetime.now() - datetime.timedelta(
            days=self.config["log_retention_days"]
        )
        try:
            with open(LOG_FILE, "r", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header is None:
                    return
                rows = [header]
                for row in reader:
                    if not row:
                        continue
                    try:
                        if datetime.datetime.fromisoformat(row[0]) >= cutoff:
                            rows.append(row)
                    except Exception:
                        rows.append(row)
            with open(LOG_FILE, "w", newline="") as f:
                csv.writer(f).writerows(rows)
        except Exception:
            pass

    def _read_totals(self) -> tuple[int, int]:
        if not LOG_FILE.exists():
            return 0, 0
        cutoff = datetime.datetime.now() - datetime.timedelta(
            days=self.config["log_retention_days"]
        )
        sent = recv = 0
        try:
            with open(LOG_FILE, "r", newline="") as f:
                for row in csv.DictReader(f):
                    try:
                        if datetime.datetime.fromisoformat(row["timestamp"]) >= cutoff:
                            sent += int(row["bytes_sent"])
                            recv += int(row["bytes_recv"])
                    except Exception:
                        pass
        except Exception:
            pass
        return sent, recv

    # ── Timer tick ────────────────────────────────────────────────────────────

    def _tick(self, _sender):
        now   = time.time()
        iface = (
            get_default_interface()
            if self.config["interface"] == "auto"
            else self.config["interface"]
        )

        # Interface changed mid-session
        if iface != self._active_iface and self._active_iface is not None:
            self._flush_log(marker=f"iface_change:{self._active_iface}->{iface}")
            self._up_samples.clear()
            self._dn_samples.clear()
        self._active_iface = iface

        if not iface:
            self.title = "↑-- ↓--"
            return

        try:
            counters = psutil.net_io_counters(pernic=True)
            cur = counters.get(iface)
        except Exception:
            return

        if cur is None:
            self.title = "↑-- ↓--"
            return

        if self._last_counters is not None:
            elapsed = now - self._last_time

            # Sleep guard: discard measurement if gap is unexpectedly large
            if elapsed > self.config["update_interval"] * 3:
                self._last_counters = cur
                self._last_time     = now
                return

            up_delta = max(0, cur.bytes_sent - self._last_counters.bytes_sent)
            dn_delta = max(0, cur.bytes_recv - self._last_counters.bytes_recv)
            up_rate  = up_delta / elapsed
            dn_rate  = dn_delta / elapsed

            self._up_samples.append(up_rate)
            self._dn_samples.append(dn_rate)

            avg_up = sum(self._up_samples) / len(self._up_samples)
            avg_dn = sum(self._dn_samples) / len(self._dn_samples)

            self._session_sent += up_delta
            self._session_recv += dn_delta
            self._peak_up = max(self._peak_up, avg_up)
            self._peak_dn = max(self._peak_dn, avg_dn)

            self._acc_sent += up_delta
            self._acc_recv += dn_delta

            if now - self._last_flush >= LOG_FLUSH_INTERVAL:
                self._flush_log()
                self._last_flush = now

            self._refresh_title(avg_up, avg_dn)
            self._refresh_session()

        self._last_counters = cur
        self._last_time     = now

    # ── Display ───────────────────────────────────────────────────────────────

    def _refresh_title(self, up: float, dn: float):
        mode  = self.config["display_mode"]
        u     = self.config["unit"]
        label = unit_label(u)
        up_s  = format_speed_short(up, u)
        dn_s  = format_speed_short(dn, u)

        if mode == "speed":
            self.title = f"↑{up_s} ↓{dn_s} {label}"
        elif mode == "totals":
            self.title = (
                f"↑{format_bytes(self._session_sent)} "
                f"↓{format_bytes(self._session_recv)}"
            )
        else:
            self.title = (
                f"↑{up_s} ↓{dn_s} {label}  "
                f"↑{format_bytes(self._session_sent)} "
                f"↓{format_bytes(self._session_recv)}"
            )

    def _refresh_session(self):
        u = self.config["unit"]
        self._mi_session.title = (
            f"Session:  ↑ {format_bytes(self._session_sent)}  "
            f"↓ {format_bytes(self._session_recv)}"
        )
        self._mi_peak.title = (
            f"Peak:     ↑ {format_speed(self._peak_up, u)}  "
            f"↓ {format_speed(self._peak_dn, u)}"
        )

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self):
        self._mi_session = rumps.MenuItem("Session:  calculating…")
        self._mi_peak    = rumps.MenuItem("Peak:     --")

        # Display mode
        dm_menu = rumps.MenuItem("Display Mode")
        self._dm_items: dict[str, rumps.MenuItem] = {}
        for key, label in [
            ("speed",  "Speed Only"),
            ("totals", "Totals Only"),
            ("both",   "Speed + Totals"),
        ]:
            it = rumps.MenuItem(label, callback=self._on_display_mode)
            it.state = int(self.config["display_mode"] == key)
            dm_menu.add(it)
            self._dm_items[key] = it

        # Units
        u_menu = rumps.MenuItem("Units")
        self._u_items: dict[str, rumps.MenuItem] = {}
        for key, label in [("mbps", "Mbps"), ("kbps", "KB/s")]:
            it = rumps.MenuItem(label, callback=self._on_unit)
            it.state = int(self.config["unit"] == key)
            u_menu.add(it)
            self._u_items[key] = it

        # Update interval
        iv_menu = rumps.MenuItem("Update Interval")
        self._iv_items: dict[str, rumps.MenuItem] = {}
        cur_iv = self.config["update_interval"]
        for label, val in INTERVALS.items():
            it = rumps.MenuItem(label, callback=self._on_interval)
            it.state = int(val == cur_iv)
            iv_menu.add(it)
            self._iv_items[label] = it

        # Interface
        iface_menu = rumps.MenuItem("Interface")
        self._iface_items: dict[str, rumps.MenuItem] = {}
        cur_iface = self.config["interface"]

        auto_it = rumps.MenuItem("Auto-detect", callback=self._on_iface)
        auto_it.state = int(cur_iface == "auto")
        iface_menu.add(auto_it)
        self._iface_items["auto"] = auto_it

        try:
            for nic in sorted(psutil.net_io_counters(pernic=True)):
                if nic.startswith("lo"):
                    continue
                it = rumps.MenuItem(nic, callback=self._on_iface)
                it.state = int(cur_iface == nic)
                iface_menu.add(it)
                self._iface_items[nic] = it
        except Exception:
            pass

        # Log settings
        log_menu = rumps.MenuItem("Log Settings")
        ret_menu = rumps.MenuItem("Log Retention")
        self._ret_items: dict[int, rumps.MenuItem] = {}
        cur_ret = self.config["log_retention_days"]
        for days in RETENTION_OPTIONS:
            suffix = " day" + ("s" if days > 1 else "")
            tag    = " (default)" if days == 7 else ""
            it = rumps.MenuItem(f"{days}{suffix}{tag}", callback=self._on_retention)
            it.state = int(cur_ret == days)
            ret_menu.add(it)
            self._ret_items[days] = it

        log_menu.add(ret_menu)
        log_menu.add(rumps.MenuItem("Open Log File", callback=self._open_log))
        log_menu.add(rumps.MenuItem("Export Log…",   callback=self._export_log))
        log_menu.add(rumps.MenuItem("Clear Log Now", callback=self._clear_log))

        # Launch at login
        self._mi_login = rumps.MenuItem("Launch at Login", callback=self._toggle_login)
        self._mi_login.state = int(PLIST_PATH.exists())

        self.menu = [
            self._mi_session,
            self._mi_peak,
            None,
            rumps.MenuItem("View Total Bandwidth…", callback=self._show_totals),
            None,
            dm_menu,
            u_menu,
            iv_menu,
            iface_menu,
            None,
            log_menu,
            None,
            self._mi_login,
            None,
            rumps.MenuItem("Quit", callback=self._quit),
        ]

    # ── Menu callbacks ────────────────────────────────────────────────────────

    def _show_totals(self, _):
        sent, recv = self._read_totals()
        days = self.config["log_retention_days"]
        rumps.alert(
            title=f"Total Bandwidth — Past {days} Day{'s' if days != 1 else ''}",
            message=(
                f"Downloaded:  {format_bytes(recv)}\n"
                f"Uploaded:    {format_bytes(sent)}\n"
                f"Total:       {format_bytes(sent + recv)}"
            ),
        )

    def _on_display_mode(self, sender):
        key_map = {
            "Speed Only":     "speed",
            "Totals Only":    "totals",
            "Speed + Totals": "both",
        }
        key = key_map.get(sender.title)
        if key:
            self.config["display_mode"] = key
            self._save_config()
            for k, it in self._dm_items.items():
                it.state = int(k == key)

    def _on_unit(self, sender):
        key_map = {"Mbps": "mbps", "KB/s": "kbps"}
        key = key_map.get(sender.title)
        if key:
            self.config["unit"] = key
            self._save_config()
            for k, it in self._u_items.items():
                it.state = int(k == key)

    def _on_interval(self, sender):
        val = INTERVALS.get(sender.title)
        if val is None:
            return
        self.config["update_interval"] = val
        self._save_config()
        for label, it in self._iv_items.items():
            it.state = int(INTERVALS[label] == val)
        self._timer.stop()
        self._timer = rumps.Timer(self._tick, val)
        self._timer.start()

    def _on_iface(self, sender):
        key = "auto" if sender.title == "Auto-detect" else sender.title
        self.config["interface"] = key
        self._save_config()
        for k, it in self._iface_items.items():
            it.state = int(k == key)
        self._last_counters = None
        self._up_samples.clear()
        self._dn_samples.clear()

    def _on_retention(self, sender):
        days = int(sender.title.split(" ")[0])
        self.config["log_retention_days"] = days
        self._save_config()
        for d, it in self._ret_items.items():
            it.state = int(d == days)
        self._trim_log()

    def _open_log(self, _):
        subprocess.run(["open", str(LOG_FILE)])

    def _export_log(self, _):
        import shutil
        dest = (
            Path.home() / "Desktop"
            / f"bandwidth_{datetime.date.today().isoformat()}.csv"
        )
        shutil.copy2(str(LOG_FILE), str(dest))
        rumps.alert(title="Export Complete", message=f"Saved to:\n{dest}")

    def _clear_log(self, _):
        if rumps.alert(
            title="Clear Log",
            message="This will permanently delete all logged bandwidth data.\nContinue?",
            ok="Clear",
            cancel="Cancel",
        ) == 1:
            self._init_log()
            rumps.alert(title="Log Cleared", message="Bandwidth log has been cleared.")

    def _toggle_login(self, _):
        if PLIST_PATH.exists():
            subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
            PLIST_PATH.unlink()
            self._mi_login.state = 0
        else:
            self._write_plist()
            subprocess.run(["launchctl", "load", str(PLIST_PATH)], capture_output=True)
            self._mi_login.state = 1

    def _write_plist(self):
        exec_path = (
            sys.executable
            if getattr(sys, "frozen", False)
            else os.path.abspath(sys.argv[0])
        )
        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        PLIST_PATH.write_text(
            f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{BUNDLE_ID}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{exec_path}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <false/>
</dict>
</plist>
"""
        )

    def _quit(self, _):
        self._flush_log()
        self._timer.stop()
        try:
            self._lock_fd.close()
            LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        rumps.quit_application()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    lock = acquire_lock()
    RealtimeUploadDownload(lock).run()
