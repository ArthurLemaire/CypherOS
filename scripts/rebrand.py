#!/usr/bin/env python3
"""Turn the OpenMinis tree in android/ into nanoMuse. Idempotent; re-run after every
upstream pull (CONTRIBUTING.md), then scripts/gen-android-icons.py.

What it changes, and only this:

- Gradle: applicationId, versionCode / versionName (the Kotlin package and namespace stay).
- The places that hard-code the package id (shortcuts, the accessibility service id).
- The product name: "Minis" -> "nanoMuse" in the 17 strings.xml and in Kotlin string
  literals (never in identifiers, paths such as /var/minis, or MinisSkills).
- The Soul defaults (agent name and header emoji).
- Links: update source, GitHub repository, issues, privacy policy.
- Colours: the iOS blues and the teal Material scheme -> the brand palette (docs/brand.md).
- Notification small icons: the launcher icon -> the flat status-bar mark; every
  notification also carries the agent's face as its large icon (Muse: the agent
  is the sender).
- "<name> is browsing": the browser banner string takes the Soul name (%1$s).
- A handful of first-run / notification strings reworded in nanoMuse's voice
  (COPY below, en + zh + zh-rTW; the other locales keep the upstream text).

Anything else is a hand edit marked `// nanoMuse:` in the file.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android" / "src" / "android"
APP = ANDROID / "app"
MAIN = APP / "src" / "main"
JAVA = MAIN / "java" / "com" / "openminis" / "app"
RES = MAIN / "res"

APP_ID = "io.github.nanomuse.app"
NAME = "nanoMuse"
VERSION_NAME = "0.1.8"
VERSION_CODE = 9
REPO = "nano-muse/nanoMuse"
REPO_URL = f"https://github.com/{REPO}"
PRIVACY_URL = f"{REPO_URL}/blob/main/docs/privacy.md"

# X-Minis-Token is a protocol header; MinisSkills is a path. The tail is an ASCII
# lookahead rather than \b so that "Minis가" (Korean particle) is still caught.
WORD = re.compile(r"(?<!X-)\bMinis(?!Skills)(?![A-Za-z0-9_])")
changed: list[str] = []


def edit(path: Path, subs: list[tuple[str, str]], count: int = 0) -> None:
    text = path.read_text(encoding="utf-8")
    new = text
    for pattern, repl in subs:
        new = re.sub(pattern, repl, new, count=count, flags=re.M)
    if new != text:
        path.write_text(new, encoding="utf-8")
        changed.append(str(path.relative_to(ROOT)))


def gradle() -> None:
    edit(
        APP / "build.gradle.kts",
        [
            (r'applicationId = "[^"]+"', f'applicationId = "{APP_ID}"'),
            (r"versionCode = \d+", f"versionCode = {VERSION_CODE}"),
            (r'versionName = "[^"]+"', f'versionName = "{VERSION_NAME}"'),
        ],
    )


def package_ids() -> None:
    edit(
        RES / "xml" / "shortcuts.xml",
        [
            (r'android:targetPackage="[^"]+"', f'android:targetPackage="{APP_ID}"'),
        ],
    )
    a11y = JAVA / "accessibility" / "MinisAccessibilityService.kt"
    edit(
        a11y,
        [
            (
                r'const val SERVICE_ID = "com\.openminis\.app/\.accessibility\.MinisAccessibilityService"',
                'val SERVICE_ID = "${BuildConfig.APPLICATION_ID}/com.openminis.app.accessibility.'
                'MinisAccessibilityService" // nanoMuse: the applicationId is not the package',
            ),
        ],
    )
    text = a11y.read_text(encoding="utf-8")
    if "import com.openminis.app.BuildConfig" not in text:
        text = text.replace("\nimport ", "\nimport com.openminis.app.BuildConfig\nimport ", 1)
        a11y.write_text(text, encoding="utf-8")


def product_name() -> None:
    for path in sorted(RES.glob("values*/strings.xml")):
        text = path.read_text(encoding="utf-8")
        new = WORD.sub(NAME, text)
        if new != text:
            ET.fromstring(new.encode("utf-8"))
            path.write_text(new, encoding="utf-8")
            changed.append(str(path.relative_to(ROOT)))
    literal = re.compile(r'"""[\s\S]*?"""|"(?:[^"\\\n]|\\.)*"')
    for path in sorted(JAVA.rglob("*.kt")):
        text = path.read_text(encoding="utf-8")
        new = literal.sub(lambda m: WORD.sub(NAME, m.group(0)), text)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(str(path.relative_to(ROOT)))


def soul_defaults() -> None:
    edit(
        JAVA / "agent" / "SoulStore.kt",
        [
            (r'const val DISPLAY_EMOJI = "✨"', 'const val DISPLAY_EMOJI = "🐾"'),
        ],
    )


def links() -> None:
    edit(
        JAVA / "data" / "UpdateChecker.kt",
        [
            (r'private const val OWNER = "[^"]+"', 'private const val OWNER = "nano-muse"'),
            (r'private const val REPO = "[^"]+"', 'private const val REPO = "nanoMuse"'),
            (
                r'const val RELEASES_URL: String = "[^"]+"',
                f'const val RELEASES_URL: String = "{REPO_URL}/releases"',
            ),
        ],
    )
    edit(
        JAVA / "ui" / "settings" / "AboutScreen.kt",
        [
            (r'"https://github\.com/OpenMinis/OpenMinis"\)', f'"{REPO_URL}")'),
        ],
    )
    edit(
        JAVA / "ui" / "settings" / "SettingsScreen.kt",
        [
            (r'"https://openminis\.github\.io/privacy-policy\.html"', f'"{PRIVACY_URL}"'),
            (r'"https://github\.com/OpenMinis/OpenMinis/issues/new"', f'"{REPO_URL}/issues/new"'),
        ],
    )


# (pattern, replacement); applied to Theme.kt only.
THEME_MAP = [
    ("0xFF528AD2", "0xFF015CFB"),  # primary
    ("0xFFB2DFDB", "0xFFE5F0FF"),  # primaryContainer
    ("0xFF00332F", "0xFF012F80"),  # onPrimaryContainer
    ("0xFF4A6360", "0xFF4F5B6E"),  # secondary
    ("0xFFCCE8E4", "0xFFDCE6F5"),  # secondaryContainer
    ("0xFF05201D", "0xFF101C2E"),  # onSecondaryContainer
    ("0xFFF5FAFA", "0xFFF2F2F7"),  # background / surface (overridden by the neutrals)
    ("0xFF171D1C", "0xFF1C1C1E"),  # onBackground / onSurface
    ("0xFFDAE5E2", "0xFFE5E5EA"),  # surfaceVariant
    ("0xFF3F4947", "0xFF3C3C43"),  # onSurfaceVariant (light) / surfaceVariant (dark)
    ("0xFF6F7977", "0xFF6E6E73"),  # outline
    ("0xFF6A94CE", "0xFF58A6FF"),  # dark primary
    ("0xFF003737", "0xFF00224D"),  # dark onPrimary
    ("0xFF1A6B6B", "0xFF1A2B4A"),  # dark primaryContainer
    ("0xFFB1CCC8", "0xFFB8C6DA"),  # dark secondary
    ("0xFF1C3532", "0xFF22304A"),  # dark onSecondary
    ("0xFF334B48", "0xFF334159"),  # dark secondaryContainer
    ("0xFF0E1514", "0xFF000000"),  # dark background / surface
    ("0xFFDEE4E2", "0xFFE5E5EA"),  # dark onBackground / onSurface
    ("0xFFBEC9C6", "0xFFC7C7CC"),  # dark onSurfaceVariant
    ("0xFF899390", "0xFF8E8E93"),  # dark outline
]

# Applied to ChatColors.kt only; light palette first, then dark.
CHAT_MAP = [
    ("userBubble = Color(0x1E787880)", "userBubble = Color(0xFFE5F0FF)"),
    ("sendButton = Color(0xFF000000)", "sendButton = Color(0xFF015CFB)"),
    ("codeBlockText = Color(0xFF34C759)", "codeBlockText = Color(0xFFE5E5EA)"),
    ("inlineCodeText = Color(0xFFFF9500)", "inlineCodeText = Color(0xFF015CFB)"),
    ("blockquoteBar = Color(0x80FF9500)", "blockquoteBar = Color(0x80015CFB)"),
    ("fabAccent = Color(0xFFB7AF96)", "fabAccent = Color(0xFF015CFB)"),
    ("userBubble = Color(0xFF2F3A5C)", "userBubble = Color(0xFF1A2B4A)"),
    ("sendButton = Color(0xFFFFFFFF)", "sendButton = Color(0xFF58A6FF)"),
    ("codeBlockText = Color(0xFF8CF38C)", "codeBlockText = Color(0xFFE5E5EA)"),
    ("inlineCodeText = Color(0xFFFF9F0A)", "inlineCodeText = Color(0xFF58A6FF)"),
    ("blockquoteBar = Color(0x80FF9F0A)", "blockquoteBar = Color(0x8058A6FF)"),
    ("fabAccent = Color(0xFF504C42)", "fabAccent = Color(0xFF58A6FF)"),
]

# The iOS system blues, wherever they are hard-coded (any alpha).
GLOBAL_MAP = [
    (r"0x([0-9A-Fa-f]{2})007AFF", r"0x\g<1>015CFB"),
    (r"0x([0-9A-Fa-f]{2})0A84FF", r"0x\g<1>58A6FF"),
    (r"#007AFF\b", "#015CFB"),
    (r"#0A84FF\b", "#58A6FF"),
]


def colours() -> None:
    edit(JAVA / "ui" / "theme" / "Theme.kt", [(re.escape(a), b) for a, b in THEME_MAP])
    edit(JAVA / "ui" / "theme" / "ChatColors.kt", [(re.escape(a), b) for a, b in CHAT_MAP], count=1)
    for path in sorted(JAVA.rglob("*.kt")) + sorted(RES.rglob("*.xml")):
        edit(path, GLOBAL_MAP)
    edit(RES / "values" / "colors.xml", [(r'(<color name="seed">)#[0-9A-Fa-f]+', r"\g<1>#015CFB")])


def notification_icons() -> None:
    for path in sorted(JAVA.rglob("*.kt")):
        edit(
            path,
            [
                (
                    r"setSmallIcon\(R\.mipmap\.ic_launcher\)",
                    "setSmallIcon(R.drawable.ic_stat_nanomuse) // nanoMuse: flat status-bar mark",
                ),
            ],
        )


FACE = re.compile(
    r"(Notification(?:Compat)?\.Builder\((\w+), [^\n]*\)\n(\s*)\.setSmallIcon\([^\n]*\n)"
    r"(?!\s*\.setLargeIcon)"
)


def notification_faces() -> None:
    """Every notification the agent sends shows its face as the large icon."""

    def add(m: re.Match[str]) -> str:
        ctx, indent = m.group(2), m.group(3)
        return (
            f"{m.group(1)}{indent}.setLargeIcon(io.github.nanomuse.identity.NanoMuseIdentity"
            f".face({ctx})) // nanoMuse: the agent is the sender\n"
        )

    for path in sorted(JAVA.rglob("*.kt")):
        text = path.read_text(encoding="utf-8")
        new = FACE.sub(add, text)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(str(path.relative_to(ROOT)))


# Reworded in nanoMuse's voice. Locale dir -> string name -> text.
COPY: dict[str, dict[str, str]] = {
    "values": {
        "sessionlist_welcome_subtitle": "Three steps, and you have an assistant that lives on your phone.",
        "onboarding_welcome_subtitle": "An AI assistant with its own terminal and browser, running on this phone.",
        "bg_service_notification_title": "nanoMuse is working",
    },
    "values-zh": {
        "sessionlist_welcome_subtitle": "三步之后，你就有一个住在手机里的助理。",
        "onboarding_welcome_subtitle": "有自己的终端和浏览器、能用这台手机的 AI 助理。",
        "bg_service_notification_title": "nanoMuse 正在工作",
    },
    "values-zh-rTW": {
        "sessionlist_welcome_subtitle": "三步之後，你就有一個住在手機裡的助理。",
        "onboarding_welcome_subtitle": "有自己的終端機和瀏覽器、能用這支手機的 AI 助理。",
        "bg_service_notification_title": "nanoMuse 正在工作",
    },
}


def reword() -> None:
    for folder, strings in COPY.items():
        subs = [
            (rf'(<string name="{name}">)[^<]*(</string>)', rf"\g<1>{text}\g<2>")
            for name, text in strings.items()
        ]
        edit(RES / folder / "strings.xml", subs)
    # "<name> is browsing": the product name becomes a placeholder in every locale.
    for path in sorted(RES.glob("values*/strings.xml")):
        edit(
            path,
            [
                (
                    rf'(<string name="browser_minis_browsing">[^<]*?){NAME}([^<]*</string>)',
                    r"\g<1>%1$s\g<2>",
                )
            ],
        )


def check() -> int:
    problems = 0
    for path in sorted(RES.glob("values*/strings.xml")):
        if WORD.search(path.read_text(encoding="utf-8")):
            print(f"  ! Minis left in {path.relative_to(ROOT)}")
            problems += 1
    leftovers = re.compile(
        r"0x[0-9A-Fa-f]{2}(007AFF|0A84FF|528AD2|6A94CE)|#007AFF|#0A84FF|nanoMuseSkills"
    )
    for path in sorted(JAVA.rglob("*.kt")) + sorted(RES.rglob("*.xml")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if leftovers.search(line):
                print(f"  ! {path.relative_to(ROOT)}:{i}: {line.strip()[:80]}")
                problems += 1
    return problems


def main() -> int:
    if not APP.is_dir():
        sys.exit(f"{APP} not found")
    gradle()
    package_ids()
    product_name()
    soul_defaults()
    links()
    colours()
    notification_icons()
    notification_faces()
    reword()
    for path in sorted(set(changed)):
        print(f"  edited {path}")
    print(f"{len(set(changed))} files changed")
    problems = check()
    print("clean" if problems == 0 else f"{problems} leftovers")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
