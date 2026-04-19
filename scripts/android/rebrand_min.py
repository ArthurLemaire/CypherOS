#!/usr/bin/env python3
"""Minimal, idempotent nanoMuse rebrand of an OpenMinis 1.13 checkout (first local APK).
Usage: rebrand_min.py <openminis-repo-root> <mark-path.txt (tile coords 0..100)>
"""
import re, sys, glob, xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(sys.argv[1]); APP = ROOT / "src/android/app"; MAIN = APP / "src/main"
MARK = Path(sys.argv[2]).read_text().strip()
APP_ID = "io.github.nanomuse.app"; NAME = "nanoMuse"
VERSION_CODE, VERSION_NAME = 1, "0.1.0"

def edit(path, subs, must=True):
    p = Path(path); s = p.read_text(encoding="utf-8"); orig = s
    for pat, rep in subs:
        s2, n = re.subn(pat, rep, s, flags=re.M)
        if n == 0 and must and not re.search(re.escape(rep) if isinstance(rep, str) and "\\" not in rep else "(?!)", s):
            print(f"  ! no match in {p.name}: {pat[:60]}")
        s = s2
    if s != orig:
        p.write_text(s, encoding="utf-8"); print(f"  edited {p.relative_to(ROOT)}")

print("== gradle")
edit(APP / "build.gradle.kts", [
    (r'applicationId = "com\.openminis\.app"', f'applicationId = "{APP_ID}"'),
    (r'versionCode = \d+', f'versionCode = {VERSION_CODE}'),
    (r'versionName = "[^"]+"', f'versionName = "{VERSION_NAME}"'),
    (r'(    compileSdk = 36\n)(?!    ndkVersion)', r'\1    ndkVersion = "27.2.12479018"\n'),
])
edit(ROOT / "src/android/gradle.properties", [
    (r'org\.gradle\.jvmargs=-Xmx2048m', 'org.gradle.jvmargs=-Xmx6144m'),
])
gp = ROOT / "src/android/gradle.properties"
if "org.gradle.parallel" not in gp.read_text():
    gp.write_text(gp.read_text().rstrip("\n") + "\norg.gradle.parallel=true\norg.gradle.caching=true\nkotlin.daemon.jvmargs=-Xmx4096m\n")

print("== package-id hard-codes")
edit(MAIN / "res/xml/shortcuts.xml", [(r'android:targetPackage="com\.openminis\.app"', f'android:targetPackage="{APP_ID}"')])
edit(MAIN / "java/com/openminis/app/accessibility/MinisAccessibilityService.kt", [
    (r'const val SERVICE_ID = "com\.openminis\.app/\.accessibility\.MinisAccessibilityService"',
     f'const val SERVICE_ID = "{APP_ID}/com.openminis.app.accessibility.MinisAccessibilityService"'),
])

print("== strings")
for f in sorted(glob.glob(str(MAIN / "res/values*/strings.xml"))):
    p = Path(f); s = p.read_text(encoding="utf-8")
    s2 = re.sub(r'\bMinis\b(?!Skills)', NAME, s)
    if s2 != s:
        p.write_text(s2, encoding="utf-8"); ET.fromstring(s2.encode("utf-8"))  # must still parse
        print(f"  {p.parent.name}: {len(re.findall(r'\\bMinis\\b(?!Skills)', s))} replaced")

print("== soul defaults")
edit(MAIN / "java/com/openminis/app/agent/SoulStore.kt", [
    (r'name = "Minis",', f'name = "{NAME}",'),
    (r'^name: "Minis"$', f'name: "{NAME}"'),
    (r'\.ifEmpty \{ "Minis" \}', f'.ifEmpty {{ "{NAME}" }}'),
    (r'const val DISPLAY_EMOJI = "✨"', 'const val DISPLAY_EMOJI = "🐾"'),
])

print("== icons")
# tile coords (0..100 == the 72dp visible area) -> 108dp adaptive canvas: x' = 18 + 0.72 x
def transform(d, k=0.72, off=18.0):
    out = []; nums = []
    def flush():
        nonlocal nums
        if nums:
            out.append(" ".join(f"{off + k*float(v):.2f}" if i % 2 == 0 else f"{off + k*float(v):.2f}" for i, v in enumerate(nums))); nums = []
    for tok in re.findall(r'[MLCZ]|-?\d*\.?\d+', d):
        if tok in "MLCZ": flush(); out.append(tok)
        else: nums.append(tok)
    flush()
    return "".join(t if t in "MLCZ" else t + " " for t in out).replace(" M", "M").replace(" L", "L").replace(" C", "C").replace(" Z", "Z").strip()
PATH108 = transform(MARK)
GX0, GX1 = 18 + 0.72*12.6, 18 + 0.72*87.8
def vector(fill_xml):
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!-- nanoMuse launcher foreground: the single-stroke N (assets/brand/nanomuse-mark.svg),
     placed on the 108dp adaptive-icon canvas; 0..100 tile units == the 72dp visible area. -->
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:aapt="http://schemas.android.com/aapt"
    android:width="108dp" android:height="108dp"
    android:viewportWidth="108" android:viewportHeight="108">
    <path android:pathData="{PATH108}"{fill_xml}
</vector>
'''
gradient = f'''>
        <aapt:attr name="android:fillColor">
            <gradient android:type="linear"
                android:startX="{GX0:.2f}" android:startY="54" android:endX="{GX1:.2f}" android:endY="54"
                android:startColor="#FF015CFB" android:endColor="#FF0186FB" />
        </aapt:attr>
    </path>'''
(MAIN / "res/drawable/ic_launcher_foreground_nm.xml").write_text(vector(gradient), encoding="utf-8")
(MAIN / "res/drawable/ic_launcher_foreground_nm_dark.xml").write_text(vector(' android:fillColor="#FFFFFFFF" />'), encoding="utf-8")
(MAIN / "res/drawable/ic_launcher_monochrome.xml").write_text(f'''<?xml version="1.0" encoding="utf-8"?>
<!-- nanoMuse themed-icon (Android 13+) silhouette: the N mark, flat white; the system re-tints it.
     Farthest point of the mark from (54,54) is ~29.3dp, inside the 33dp themed-icon circle. -->
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp" android:height="108dp"
    android:viewportWidth="108" android:viewportHeight="108">
    <path android:fillColor="#FFFFFFFF" android:pathData="{PATH108}" />
</vector>
''', encoding="utf-8")
def adaptive(bg, fg):
    return f'''<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="{bg}" />
    <foreground android:drawable="{fg}" />
    <monochrome android:drawable="@drawable/ic_launcher_monochrome" />
</adaptive-icon>
'''
(MAIN / "res/mipmap-anydpi-v26/ic_launcher.xml").write_text(adaptive("@color/ic_launcher_background", "@drawable/ic_launcher_foreground_nm"), encoding="utf-8")
(MAIN / "res/mipmap-anydpi-v26/ic_launcher_classic_light.xml").write_text(adaptive("@color/ic_launcher_bg_force_light", "@drawable/ic_launcher_foreground_nm"), encoding="utf-8")
(MAIN / "res/mipmap-anydpi-v26/ic_launcher_classic_dark.xml").write_text(adaptive("@color/ic_launcher_bg_force_dark", "@drawable/ic_launcher_foreground_nm_dark"), encoding="utf-8")
for f, subs in [
    (MAIN / "res/values/ic_launcher_background.xml", [(r'(name="ic_launcher_background">)#[0-9A-Fa-f]+', r'\1#FFFFFF')]),
    (MAIN / "res/values-night/ic_launcher_background.xml", [(r'(name="ic_launcher_background">)#[0-9A-Fa-f]+', r'\1#FFFFFF')]),
    (MAIN / "res/values/ic_launcher_alt_colors.xml", [(r'(name="ic_launcher_bg_force_light">)#[0-9A-Fa-f]+', r'\1#FFFFFF'), (r'(name="ic_launcher_bg_force_dark">)#[0-9A-Fa-f]+', r'\1#0F1B33')]),
]:
    edit(f, subs, must=False)
print("  icons written")

print("== local.properties")
(ROOT / "src/android/local.properties").write_text("sdk.dir=/ssd/software/android-studio/Android/SDK\n")
print("done")
