#!/usr/bin/env python3
"""Record the phone screen with real frame timing, through scrcpy's server.

    python3 docs/promo/film/record.py 03-approval             # Ctrl-C to stop → ~/nm-rec/03-approval.mp4
    python3 docs/promo/film/record.py 03-approval --out ~/nm-rec --serial <adb-serial>
    python3 docs/promo/film/record.py --statusbar on|off       # 09:41, full battery, Wi‑Fi, nothing else

Why not `adb shell screenrecord`: on ColorOS it crashes (SIGSEGV) as soon as it starts, and on
every phone it stamps frames at a fixed rate whether or not the screen changed. The scrcpy
server (the same .jar the scrcpy client pushes, GPL/Apache, https://github.com/Genymobile/scrcpy)
sends an H.264 frame only when the screen changes and puts the real presentation time in front
of each one. We keep those times: the raw stream goes into a Matroska file with the original
timestamps (PyAV), then ffmpeg makes a constant 30 fps MP4 that build.py can cut. Pauses look like
pauses; a two-second model wait is two seconds on screen.

Setup, once:
    pip install --user av
    curl -LO https://github.com/Genymobile/scrcpy/releases/download/v4.1/scrcpy-server-v4.1
    adb -s <serial> push scrcpy-server-v4.1 /data/local/tmp/scrcpy-server.jar
The frame header layout is the one scrcpy 4.x uses (12 bytes: pts+flags as u64, size as u32;
bit 62 marks a config packet, bit 61 a key frame).

The status bar: --statusbar on enters SystemUI's demo mode (09:41, 100 %, Wi‑Fi, no
notifications) the way platform screenshots do; off leaves it. On ColorOS, never send
`network -e mobile hide` — it crashes SystemUI; the script does not.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import struct
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

PORT = 27183
FLAG_CONFIG = 1 << 62
PTS_MASK = (1 << 61) - 1
SERVER_CMD = (
    "CLASSPATH=/data/local/tmp/scrcpy-server.jar app_process / com.genymobile.scrcpy.Server 4.1 "
    "log_level=info video=true audio=false control=false tunnel_forward=true cleanup=false "
    "send_device_meta=false send_dummy_byte=false send_stream_meta=false send_frame_meta=true "
    "video_bit_rate=16000000 max_fps=60 video_codec=h264"
)


def adb(serial: str | None, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["adb"] + (["-s", serial] if serial else []) + list(args)
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def statusbar(serial: str | None, on: bool) -> None:
    def demo(*kv: str) -> None:
        adb(serial, "shell", "am", "broadcast", "-a", "com.android.systemui.demo", "-e", "command", *kv, check=False)

    if not on:
        demo("exit")
        return
    adb(serial, "shell", "settings", "put", "global", "sysui_demo_allowed", "1", check=False)
    demo("enter")
    demo("clock", "-e", "hhmm", "0941")
    demo("battery", "-e", "level", "100", "-e", "plugged", "false")
    demo("network", "-e", "wifi", "show", "-e", "level", "4", "-e", "fully", "true")
    demo("status", "-e", "volume", "hide", "-e", "bluetooth", "hide", "-e", "mute", "hide")
    demo("notifications", "-e", "visible", "false")


def record(serial: str | None, name: str, out: Path) -> tuple[Path, Path]:
    """Read the framed stream until SIGINT; returns (raw Annex-B file, pts file)."""
    out.mkdir(parents=True, exist_ok=True)
    adb(serial, "forward", f"tcp:{PORT}", "localabstract:scrcpy")
    server_log = open(out / f"{name}.server.log", "w")
    srv = subprocess.Popen(["adb"] + (["-s", serial] if serial else []) + ["shell", SERVER_CMD], stdout=server_log, stderr=subprocess.STDOUT)

    sock = None
    head = b""
    for _ in range(60):
        try:
            sock = socket.create_connection(("127.0.0.1", PORT), timeout=2)
            sock.settimeout(3)
            head = sock.recv(12, socket.MSG_WAITALL)
            if len(head) == 12:
                break
            sock.close()
            sock = None
        except (ConnectionRefusedError, socket.timeout, ConnectionResetError):
            if sock:
                sock.close()
                sock = None
        time.sleep(0.25)
    if sock is None:
        srv.kill()
        raise SystemExit("could not connect to the scrcpy server (is scrcpy-server.jar in /data/local/tmp?)")
    sock.settimeout(0.5)

    running = True

    def stop(*_: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    def read_exact(n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
            except socket.timeout:
                if not running:
                    raise EOFError
                continue
            if not chunk:
                raise EOFError
            buf += chunk
        return buf

    raw_path, pts_path = out / f"{name}.h264", out / f"{name}.pts"
    frames, first = 0, None
    print(f"recording {name} — Ctrl-C to stop", flush=True)
    with open(raw_path, "wb") as raw, open(pts_path, "w") as pts_file:
        try:
            while running:
                pf, size = struct.unpack(">QI", head)
                data = read_exact(size)
                raw.write(data)
                if not pf & FLAG_CONFIG:
                    pts = pf & PTS_MASK
                    if first is None:
                        first = pts
                    pts_file.write(f"{pts - first}\n")
                    frames += 1
                head = read_exact(12)
        except EOFError:
            pass
        finally:
            sock.close()
            srv.terminate()
            adb(serial, "shell", "for p in $(pidof app_process); do kill $p; done", check=False)
    print(f"{frames} frames", flush=True)
    return raw_path, pts_path


def mux(raw_path: Path, pts_path: Path, mp4: Path) -> None:
    """Annex-B + per-frame times → MKV with the real timestamps → 30 fps CFR MP4."""
    try:
        import av
    except ImportError:
        raise SystemExit("PyAV is needed to keep the real timestamps: pip install --user av")
    pts = [int(x) for x in pts_path.read_text().split()]
    mkv = mp4.with_suffix(".mkv")
    inp = av.open(str(raw_path))
    ist = inp.streams.video[0]
    outc = av.open(str(mkv), "w")
    ost = outc.add_stream(template=ist)
    n = 0
    for pkt in inp.demux(ist):
        if pkt.size == 0 or n >= len(pts):
            continue
        pkt.stream = ost
        pkt.time_base = Fraction(1, 1_000_000)
        pkt.pts = pkt.dts = pts[n]
        pkt.duration = (pts[n + 1] - pts[n]) if n + 1 < len(pts) else 100_000
        outc.mux(pkt)
        n += 1
    outc.close()
    inp.close()
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(mkv), "-vsync", "cfr", "-r", "30",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4),
    ], check=True)
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)],
                         capture_output=True, text=True).stdout.strip()
    print(f"{mp4} ({float(dur):.1f}s, {n} frames kept with their own times; {mkv.name} is the VFR original)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?", help="scene name, e.g. 03-approval → NAME.mp4")
    ap.add_argument("--out", type=Path, default=Path(os.environ.get("NM_REC", "~/nm-rec")).expanduser())
    ap.add_argument("--serial", default=os.environ.get("DEV") or None, help="adb serial (default: the only device)")
    ap.add_argument("--statusbar", choices=["on", "off"], help="only set the demo status bar, then exit")
    args = ap.parse_args()

    if args.statusbar:
        statusbar(args.serial, args.statusbar == "on")
        return 0
    if not args.name:
        ap.error("a scene name is needed")
    raw_path, pts_path = record(args.serial, args.name, args.out)
    mux(raw_path, pts_path, args.out / f"{args.name}.mp4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
