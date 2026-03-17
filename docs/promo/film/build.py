#!/usr/bin/env python3
"""Cut the phone recordings into the launch film.

    python3 docs/promo/film/build.py --raw ~/nm-rec            # everything: 16:9 zh + en, 9:16 × N, README GIF
    python3 docs/promo/film/build.py --raw ~/nm-rec --only wide-zh,gif
    python3 docs/promo/film/build.py --raw ~/nm-rec --list     # print the scenes and which recordings are present

The raw material is one .mp4 per scene, recorded with docs/promo/film.md §2 (scrcpy-server on
the phone, real frame timing, 1080 × 2400, 30 fps CFR). SCENES below says which file each scene
comes from, which seconds of it to keep, what to write beside the phone, and which rectangles to
pixelate (hostnames, addresses). A scene whose recording is not in --raw is skipped and listed,
so the film can be built from whatever has been shot so far.

Outputs go to docs/promo/film/out/ (git-ignored except the GIF):
    nanomuse-launch-zh.mp4     1920 × 1080, Chinese on-screen copy, no narration
    nanomuse-launch-en.mp4     the same cut with the English copy
    vertical/<scene>.mp4       1080 × 1920, one per scene, for 视频号 / 抖音 / Shorts
    nanomuse-approval.gif      6 s, 400 px wide, for the README and the social preview
    stills/<scene>-<n>.png     first frame of every kept range, for picking thumbnails

Needs ffmpeg (4.2 is enough: drawtext, boxblur, overlay, fade, concat), Pillow, and Noto Sans CJK
for the Chinese copy. Music is not mixed in here — the file is delivered silent; film.md §5 says
which CC0 tracks to lay under it and where.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
ROOT = HERE.parents[2]

FONT_ZH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_ZH_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
DRAGON = ROOT / "android/src/android/app/src/main/res/drawable-nodpi/nm_avatar_idle.webp"
ICON = ROOT / "docs/app-icon.png"

BG = "0xf5f5f7"
FG = "0x1d1d1f"
FG2 = "0x6e6e73"
ACTION = "0x0a66e4"

SRC_W, SRC_H = 1080, 2400
FPS = 30
FADE = 0.4


@dataclass
class Range:
    start: float
    end: float
    blur: list[tuple[int, int, int, int]] = field(default_factory=list)  # x, y, w, h in source pixels


@dataclass
class Scene:
    slug: str
    source: str  # file name under --raw
    ranges: list[Range]
    kicker: tuple[str, str]  # zh, en
    title: tuple[list[str], list[str]]  # lines, zh / en
    caption: tuple[list[str], list[str]]


# Rectangles on the pairing screen where the host prints the computer's name: the row in the
# "paired computers" list and the "Paired with <name>" line under the form.
PAIR_BLUR = [(160, 680, 130, 70), (76, 1850, 270, 60)]

SCENES: list[Scene] = [
    Scene(
        "name", "02-name.mp4",
        [Range(133.0, 143.2), Range(185.4, 191.6)],
        ("第一次见面", "First conversation"),
        (["它问你怎么称呼，", "再给自己起名字。"], ["It asks what to call you,", "then names itself."]),
        (["三个名字里挑一个，或者自己起。", "从这里开始，它就是小知了。"],
         ["Pick one of three, or type your own.", "From here on, it is 小知."]),
    ),
    Scene(
        "approval", "03-approval.mp4",
        [Range(281.0, 292.6), Range(316.0, 321.8)],
        ("关键处先问", "Asks first"),
        (["删之前，", "先停下来问你。"], ["Before it deletes,", "it stops and asks."]),
        (["只这一次、本次对话，还是对这个目录一直允许，你定。", "密码和验证码永远你自己输。"],
         ["Once, for this chat, or always for this folder — your call.", "Passwords and codes are always yours to type."]),
    ),
    Scene(
        "memory", "04-memory.mp4",
        [Range(6.0, 24.0)],
        ("记得你", "Remembers you"),
        (["随口一句，", "它记进 USER.md。"], ["Say it once;", "it goes into USER.md."]),
        (["它记住的每一句都是手机里一个能打开的文件：", "能看，能改，能删。"],
         ["Every memory is a plain file on the phone:", "read it, edit it, delete it."]),
    ),
    Scene(
        "pair", "06-pair.mp4",
        [Range(2.0, 14.0), Range(46.0, 56.0, PAIR_BLUR)],
        ("电脑 · 0.1.13 起", "Your computer · since 0.1.13"),
        (["电脑上跑一个 Python 文件，", "手机上填六位码。"], ["One Python file on the computer,", "a six-digit code on the phone."]),
        (["之后手机上的一句话，可以在电脑上跑命令、取放文件、开网页。", "只走局域网；电脑永远碰不到手机。"],
         ["From then on a sentence on the phone runs commands, moves files, opens pages there.", "Local network only; the computer can never reach the phone."]),
    ),
    # Shot on the phone once USB debugging is re-authorised (film.md §3): the hands on the clock
    # app, a sentence carried out on the computer, the morning feed.
    Scene(
        "hands", "07-hands.mp4",
        [Range(0.0, 20.0)],
        ("动手操作屏幕 · 0.1.12 起", "Hands · since 0.1.12"),
        (["没有 API 的 App，", "它自己看屏幕点。"], ["No API?", "It uses the screen."]),
        (["看一眼截图，做一步，再看一眼。「停止」一直在屏幕上。", "登录和验证码交还给你；付款、发送、删除前照样先问。"],
         ["Look, act, look again. Stop is always on screen.", "Logins go back to you; paying, sending, deleting still ask first."]),
    ),
    Scene(
        "reach", "08-reach.mp4",
        [Range(0.0, 20.0)],
        ("电脑", "Your computer"),
        (["手机上说一句，", "电脑上干完。"], ["Say it on the phone.", "Done on the computer."]),
        (["跑命令、拿文件、开网页、看一眼屏幕，结果和审批都回到手机上。"],
         ["Commands, files, pages, a glance at the screen — results and approvals come back to the phone."]),
    ),
    Scene(
        "feed", "09-feed.mp4",
        [Range(0.0, 16.0)],
        ("写给你的动态", "A feed written for you"),
        (["每天早上几条短帖，", "来自它对你的了解。"], ["A few posts every morning,", "from what it knows about you."]),
        (["想换个方向，说一句就行。"], ["Want a different angle? Just say so."]),
    ),
]

INTRO = {
    "zh": (["nanoMuse"], ["完全开源的 Muse 式个人智能体，", "装在你自己的手机上。"], ["Android · 0.1.15 · GPL-3.0-or-later"]),
    "en": (["nanoMuse"], ["A fully open-source, Muse-style personal agent", "for every device you own."], ["Android today · 0.1.15 · GPL-3.0-or-later"]),
}
OUTRO = {
    "zh": (["nanomuse.cn"], ["下载、源码和每一版的说明都在这里。"],
           ["nanoMuse 是独立的社区项目，与 Meta 无关；Muse 是 Meta Platforms, Inc. 的商标。", "基于 OpenMinis 1.13（GPL-3.0）修改，整个仓库 GPL-3.0-or-later。"]),
    "en": (["github.com/nano-muse/nanoMuse"], ["Releases, source and notes for every version."],
           ["An independent community project, not affiliated with Meta; Muse is a trademark of Meta Platforms, Inc.", "Based on OpenMinis 1.13 (GPL-3.0); the whole repository is GPL-3.0-or-later."]),
}


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def esc(s: str) -> str:
    """Escape for a drawtext text= value inside a filter graph."""
    return s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\\\\\'").replace("%", "\\%").replace(",", "\\,")


def text(s: str, x: str, y: int, size: int, color: str, bold: bool = False) -> str:
    font = FONT_ZH_BOLD if bold else FONT_ZH
    return f"drawtext=fontfile={font}:text='{esc(s)}':x={x}:y={y}:fontsize={size}:fontcolor={color}"


def blur_chain(boxes: list[tuple[int, int, int, int]]) -> tuple[str, str]:
    """Filter graph that pixelates the boxes on the [src] stream; returns (graph, out_label)."""
    if not boxes:
        return "", "[src]"
    parts = []
    cur = "[src]"
    for i, (x, y, w, h) in enumerate(boxes):
        parts.append(f"{cur}split[b{i}a][b{i}b]")
        parts.append(f"[b{i}b]crop={w}:{h}:{x}:{y},scale={max(1, w // 14)}:{max(1, h // 14)},scale={w}:{h}:flags=neighbor,boxblur=2[b{i}c]")
        parts.append(f"[b{i}a][b{i}c]overlay={x}:{y}[m{i}]")
        cur = f"[m{i}]"
    return ";".join(parts) + ";", cur


def cut_range(src: Path, r: Range, dst: Path) -> float:
    """Extract one range as a 1080 × 2400 clip with the blur applied; returns its duration."""
    graph, label = blur_chain(r.blur)
    dur = r.end - r.start
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{r.start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
        "-filter_complex", f"[0:v]setpts=PTS-STARTPTS,fps={FPS}[src];{graph}{label}null[v]" if graph else f"[0:v]setpts=PTS-STARTPTS,fps={FPS}[v]",
        "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "14", "-pix_fmt", "yuv420p", str(dst),
    ])
    return dur


def concat(parts: list[Path], dst: Path, reencode: bool = False) -> None:
    lst = dst.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if reencode:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    else:
        cmd += ["-c", "copy", "-movflags", "+faststart"]
    run(cmd + [str(dst)])
    lst.unlink()


def phone_frame(ph_w: int, ph_h: int, work: Path) -> tuple[Path, Path]:
    """A dark rounded bezel and a rounded alpha mask for a phone of ph_w × ph_h, drawn with Pillow."""
    from PIL import Image, ImageDraw

    pad, radius = 12, 56
    frame = Image.new("RGBA", (ph_w + 2 * pad, ph_h + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(frame).rounded_rectangle((0, 0, frame.width - 1, frame.height - 1), radius + pad, fill=(17, 17, 17, 255))
    mask = Image.new("L", (ph_w, ph_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, ph_w - 1, ph_h - 1), radius, fill=255)
    fp, mp = work / f"frame-{ph_w}x{ph_h}.png", work / f"mask-{ph_w}x{ph_h}.png"
    frame.save(fp)
    mask.save(mp)
    return fp, mp


def framed_phone(phone: Path, ph_w: int, ph_h: int, x: str, y: str, work: Path) -> tuple[list[str], str]:
    """Inputs and filter-graph prefix that put the framed, rounded phone on [bg] and leave [c]."""
    fp, mp = phone_frame(ph_w, ph_h, work)
    inputs = ["-i", str(phone), "-i", str(fp), "-i", str(mp)]
    graph = (
        f"[1:v]scale={ph_w}:{ph_h}[ph];[ph][3:v]alphamerge[phr];"
        f"[bg][2:v]overlay=({x})-12:({y})-12[bgf];[bgf][phr]overlay={x}:{y}[c];"
    )
    return inputs, graph


def scene_clip(scene: Scene, phone: Path, dur: float, lang: str, dst: Path, work: Path) -> None:
    """Compose the 16:9 frame: copy on the left, the phone on the right, fades at both ends."""
    i = 0 if lang == "zh" else 1
    ph_h = 960
    ph_w = round(SRC_W * ph_h / SRC_H)
    ph_x, ph_y = 1920 - 160 - ph_w, (1080 - ph_h) // 2
    lines = [text(scene.kicker[i], "160", 300, 30, ACTION, bold=True)]
    y = 352
    for ln in scene.title[i]:
        lines.append(text(ln, "160", y, 66 if lang == "zh" else 60, FG, bold=True))
        y += 92 if lang == "zh" else 80
    y += 26
    for ln in scene.caption[i]:
        lines.append(text(ln, "160", y, 30 if lang == "zh" else 28, FG2))
        y += 50
    brand = text("nanoMuse · nanomuse.cn" if lang == "zh" else "nanoMuse · github.com/nano-muse/nanoMuse", "160", 990, 26, FG2)
    inputs, prefix = framed_phone(phone, ph_w, ph_h, str(ph_x), str(ph_y), work)
    graph = (
        f"color=c={BG}:s=1920x1080:r={FPS}:d={dur:.3f}[bg];{prefix}"
        f"[c]{','.join(lines + [brand])},"
        f"fade=t=in:st=0:d={FADE},fade=t=out:st={max(0.0, dur - FADE):.3f}:d={FADE}[v]"
    )
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "nullsrc=s=16x16:d=0.1", *inputs,
        "-filter_complex", graph, "-map", "[v]", "-t", f"{dur:.3f}", "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", str(dst),
    ])


def card_clip(spec: tuple[list[str], list[str], list[str]], dur: float, dst: Path, with_dragon: bool) -> None:
    """A title or end card: big line, lead lines, fine print; the dragon on the right when asked."""
    big, lead, fine = spec
    lines = []
    y = 380
    for ln in big:
        size = 110 if len(ln) <= 14 else 78  # a URL as the big line has to fit in 1600 px
        lines.append(text(ln, "160", y + (110 - size) // 2, size, FG, bold=True))
        y += 150
    y += 10
    for ln in lead:
        lines.append(text(ln, "160", y, 42, FG))
        y += 64
    y += 24
    for ln in fine:
        lines.append(text(ln, "160", y, 24, FG2))
        y += 38
    inputs = ["-f", "lavfi", "-i", f"color=c={BG}:s=1920x1080:r={FPS}:d={dur:.3f}"]
    graph = "[0:v]"
    if with_dragon:
        inputs += ["-i", str(DRAGON)]
        graph = "[1:v]scale=560:560[d];[0:v][d]overlay=1920-160-560:(1080-560)/2[c];[c]"
    graph += ",".join(lines) + f",fade=t=in:st=0:d={FADE},fade=t=out:st={max(0.0, dur - FADE):.3f}:d={FADE}[v]"
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", graph, "-map", "[v]", "-t", f"{dur:.3f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", str(dst)])


def vertical_clip(scene: Scene, phone: Path, dur: float, dst: Path, work: Path) -> None:
    """9:16: the phone nearly full height, the Chinese title above it, the brand below."""
    ph_h = 1460
    ph_w = round(SRC_W * ph_h / SRC_H)
    lines = [text(scene.kicker[0], "(w-text_w)/2", 120, 34, ACTION, bold=True)]
    y = 176
    for ln in scene.title[0]:
        lines.append(text(ln, "(w-text_w)/2", y, 62, FG, bold=True))
        y += 84
    brand = text("nanoMuse · nanomuse.cn", "(w-text_w)/2", 1840, 28, FG2)
    inputs, prefix = framed_phone(phone, ph_w, ph_h, f"(1080-{ph_w})/2", "350", work)
    graph = (
        f"color=c={BG}:s=1080x1920:r={FPS}:d={dur:.3f}[bg];{prefix}[c]{','.join(lines + [brand])},"
        f"fade=t=in:st=0:d={FADE},fade=t=out:st={max(0.0, dur - FADE):.3f}:d={FADE}[v]"
    )
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "nullsrc=s=16x16:d=0.1", *inputs,
         "-filter_complex", graph, "-map", "[v]", "-t", f"{dur:.3f}", "-an",
         "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", str(dst)])


def gif(raw: Path, dst: Path) -> None:
    """Six seconds of the approval sheet sliding in, 400 px wide, 12 fps, two-pass palette."""
    src = raw / "03-approval.mp4"
    if not src.exists():
        print("gif: 03-approval.mp4 not in --raw, skipped")
        return
    pal = dst.with_suffix(".palette.png")
    common = ["-ss", "286.5", "-t", "6", "-i", str(src)]
    run(["ffmpeg", "-y", "-loglevel", "error", *common, "-vf", "fps=12,scale=400:-1:flags=lanczos,palettegen=max_colors=160:stats_mode=diff", str(pal)])
    run(["ffmpeg", "-y", "-loglevel", "error", *common, "-i", str(pal), "-lavfi", "fps=12,scale=400:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle", str(dst)])
    pal.unlink()
    print(f"{dst} ({dst.stat().st_size // 1024} KB)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, required=True, help="directory with the scene recordings (02-name.mp4, ...)")
    ap.add_argument("--only", default="", help="comma-separated: wide-zh, wide-en, vertical, gif, stills")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if shutil.which("ffmpeg") is None:
        print("ffmpeg not found", file=sys.stderr)
        return 2

    present = [s for s in SCENES if (args.raw / s.source).exists()]
    missing = [s for s in SCENES if not (args.raw / s.source).exists()]
    if args.list or not present:
        for s in SCENES:
            mark = "ok " if s in present else "-- "
            print(f"{mark}{s.slug:10s} {s.source:18s} " + ", ".join(f"{r.start:.1f}-{r.end:.1f}" for r in s.ranges))
        return 0 if present else 1

    want = {w.strip() for w in args.only.split(",") if w.strip()} or {"wide-zh", "wide-en", "vertical", "gif", "stills"}
    work = OUT / "work"
    work.mkdir(parents=True, exist_ok=True)
    (OUT / "vertical").mkdir(exist_ok=True)
    (OUT / "stills").mkdir(exist_ok=True)

    phones: dict[str, tuple[Path, float]] = {}
    for s in present:
        parts, total = [], 0.0
        for n, r in enumerate(s.ranges):
            p = work / f"{s.slug}-{n}.mp4"
            total += cut_range(args.raw / s.source, r, p)
            parts.append(p)
            if "stills" in want:
                run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(p), "-frames:v", "1", str(OUT / "stills" / f"{s.slug}-{n}.png")])
        phone = work / f"{s.slug}.mp4"
        concat(parts, phone)
        phones[s.slug] = (phone, total)
        print(f"{s.slug}: {total:.1f}s from {s.source}")

    for lang in ("zh", "en"):
        if f"wide-{lang}" not in want:
            continue
        clips = []
        p = work / f"intro-{lang}.mp4"
        card_clip(INTRO[lang], 4.0, p, with_dragon=True)
        clips.append(p)
        for s in present:
            phone, dur = phones[s.slug]
            p = work / f"{s.slug}-{lang}.mp4"
            scene_clip(s, phone, dur, lang, p, work)
            clips.append(p)
        p = work / f"outro-{lang}.mp4"
        card_clip(OUTRO[lang], 5.0, p, with_dragon=False)
        clips.append(p)
        dst = OUT / f"nanomuse-launch-{lang}.mp4"
        concat(clips, dst)
        total = 4.0 + 5.0 + sum(d for _, d in phones.values())
        print(f"{dst} ({total:.0f}s, {dst.stat().st_size // 1024 // 1024} MB)")

    if "vertical" in want:
        for s in present:
            phone, dur = phones[s.slug]
            dst = OUT / "vertical" / f"{s.slug}.mp4"
            vertical_clip(s, phone, dur, dst, work)
            print(f"{dst} ({dur:.0f}s)")

    if "gif" in want:
        gif(args.raw, OUT / "nanomuse-approval.gif")

    if missing:
        print("not shot yet, skipped: " + ", ".join(f"{s.slug} ({s.source})" for s in missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
