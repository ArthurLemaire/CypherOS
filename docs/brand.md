# nanoMuse brand

Decided 2026-09-24. The app icon and the in-app colour system are one decision: the palette
is derived from the icon so the whole app matches the tile on the home screen.

## The mark

One continuous pen stroke that reads as an **N**: a hooked entry, one rounded peak, a long
diagonal, a tight valley, and an upward exit. It follows the same visual grammar as Muse's
single-stroke mark (Muse's is an M with three arches; ours is an N with one) — the same way
OpenManus rhymes with Manus while being a different gesture. The mark is abstract on purpose:
it is a gesture first and a letter second.

- Source of truth: `assets/brand/nanomuse-icon-source-1024.png` (final render, white squircle on
  brand blue). Everything else is derived from it.
- `assets/brand/nanomuse-mark.svg` — the stroke alone, traced as a single filled path, viewBox
  `0 0 100 100` in tile coordinates, gradient fill.
- `assets/brand/nanomuse-icon.svg` — white squircle tile (`rx=27`) + mark. This is the app icon.
- `assets/brand/nanomuse-icon-on-blue.svg` — the icon on the brand-blue backdrop, for
  store listings, README hero, splash.
- `assets/brand/nanomuse-mark-rgba-688.png` — the stroke with alpha, 688 px, raster fallback.

The icon is **not** the mascot. The red panda (`web/src/components/redPandaShapes.ts`) is the
default chat avatar only, and users will be able to replace it. Never put the red panda on the
launcher icon, and never put the N mark in the chat as a face.

## Colour

Measured from the icon.

| Token | Value | Use |
|---|---|---|
| `brand.stroke.start` | `#015CFB` | left end of the mark's gradient |
| `brand.stroke.end` | `#0186FB` | right end of the mark's gradient |
| `brand.blue` | `#0078FD` | backdrop behind the tile; splash; hero backgrounds |
| `tile` | `#FFFFFF` | icon tile |

### Light theme

| Token | Value | Contrast | Use |
|---|---|---|---|
| `primary` | `#015CFB` | 5.35 on white | links, primary buttons (white text), active tab, send button, status line |
| `primary.container` | `#E5F0FF` | — | user bubble, selected rows, chips |
| `primary.tint` | `#EEF5FF` | — | subtle highlighted surfaces |
| `bg.grouped` | `#F2F2F7` | — | page background (unchanged from OpenMinis) |
| `surface` | `#FFFFFF` | — | cards, input |

### Dark theme

| Token | Value | Contrast | Use |
|---|---|---|---|
| `primary` | `#58A6FF` | 8.3 on `#000`, 6.7 on `#1C1C1E` | links, buttons (black text), active tab, status line |
| `primary.container` | `#1A2B4A` | — | user bubble |
| `bg` / `surface` / `surface.2` | `#000000` / `#1C1C1E` / `#2C2C2E` | — | unchanged from OpenMinis |

Rules: one accent hue only. Code blocks, thinking text and links that OpenMinis coloured with
iOS blue, orange and green become `primary` plus neutrals. Rust orange from the red panda stays
inside the avatar; it is not a UI colour.

## Android mapping (done in S1)

- Adaptive icon: background layer = solid `#FFFFFF`; foreground layer = the mark as a
  `VectorDrawable` whose `fillColor` is the two-stop linear gradient above; monochrome layer =
  the same path with a flat fill (Android tints it).
- Icon skins (activity aliases kept from OpenMinis): *Auto* = white tile; *Light* = white tile;
  *Dark* = `#0F1B33` tile with a white mark.
- Notification small icon: the mark, flat white, 24 dp.
- Never ship the old OpenMinis icon, name or the letter-n drafts.

## Don'ts

- Don't recolour the mark outside the blue gradient / flat white / flat black.
- Don't rotate, outline, or add a shadow to the stroke.
- Don't place the mark on the brand blue without the white tile (contrast).
- Don't use Meta's Muse mark, name or blue as an asset; the kinship is in the gesture only.
