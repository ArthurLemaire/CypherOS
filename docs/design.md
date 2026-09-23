# Design: what nanoMuse takes from Muse, and where it differs

A study of Muse's screens — the announcement, the walkthrough and sizzle videos, the app screenshots Meta published — and the choices nanoMuse made from it. It exists so that the app stays coherent as it grows and so that a contributor can tell "on purpose" from "not yet". Nothing here is Meta's code or assets; the plush dolls, the red panda and the layouts are the project's own.

## What Muse looks like

**Surfaces.** Near-white (`#fcfcfc`-ish) in light mode and near-black in dark; no gradients, no card shadows to speak of. Depth comes from one step of grey (a `surface-2`) for bubbles, chips and the tab bar. One accent, a saturated blue, used sparingly: the send button, links, the status line while something runs, the selected tab.

**Type.** Meta's own *Optimistic*; large, friendly, tight letter-spacing on headings, generous line-height in bubbles. Everything is set in one family at three or four sizes.

**Chat.** The agent's bubbles are grey, yours are light blue, both with large radii. Tool use is not hidden: a small chip per action ("Checking price", "Found 3 options") that opens into detail. Approval requests are cards inside the conversation, with the exact action spelled out and buttons that say what they do. Files the agent made appear as tiles with a preview.

**The avatar.** A plush doll with a name — Meta's launch examples were Veda, Sunny and others — photographed against a warm plain background. It sits at the top of the chat inside a circle, with the agent's name under it and a one-line status ("Checking price") under that. It is not one picture: the doll changes pose with what the agent is doing — at a laptop with headphones on while it works, waving when it greets you, idle otherwise — and it moves a little: a sway, a blink. Tapping it opens a sheet: the doll large, the same status, a *Stop* control on the running task, then a segmented control — activity, approvals, permissions, upcoming — and the list for the selected one, grouped by day.

**Navigation.** A floating bar at the bottom with five icons and no labels: Chat, Feed, Ideas, Goals, Library. Chat is the home. Everything else the agent has — memory, connections, settings — lives behind the avatar.

**Feed, Ideas, Goals, Library.** Feed: posts written for you, with a place to say what you want more of. Ideas: a grid of suggestions grouped by area, tap to send. Goals: a list with progress, each opening to a plan with steps and a next check-in. Library: what the agent made, newest first, with previews.

**Motion.** Little. The status line changes; a chip appears; the avatar sways. No spinners except a small one next to the status.

## What nanoMuse does with it

| Muse | nanoMuse | Where |
|---|---|---|
| Near-white / near-black, one blue | The same palette: `bg`, `surface-2`, `fg`, `muted`, accent `#0064d4`; dark mode by `prefers-color-scheme` | `web/src/index.css`, `android/…/values/colors.xml` |
| Optimistic | [Figtree](https://github.com/erikdkennedy/figtree) (OFL), bundled; close in proportions and warmth | `web/public/fonts/` |
| Grey / light-blue bubbles, chips for tool use, cards for approvals | The same; chips open to the tool call, cards carry the summary the Sentinel wrote and the scope buttons (once, this task, always) | `web/src/screens/ChatScreen.tsx`, `web/src/components/` |
| The plush doll that changes pose | The **red panda**, an SVG drawn live with a pose per state; six plush dolls (Sunny, Moss, Sky, Fox, Bolt, Plum) and an emoji as alternatives | `web/src/components/RedPanda.tsx`, `web/public/avatars/` |
| Name and status under the avatar; tap for the sheet | The same header; the sheet has the avatar large, the status, *Stop*, four buttons (approvals, activity, permissions, upcoming) and rows for memory, skills, connections, settings | `web/src/components/MuseSheet.tsx` |
| Five-icon floating bar | The same five: Chat, Feed, Ideas, Goals, Library | `web/src/App.tsx` |
| Little motion | Breathing / sway / hop for the dolls and the emoji; the panda's own poses; everything off under `prefers-reduced-motion` | `web/src/index.css`, `RedPanda.css` |

## The red panda

Muse's doll says "there is someone here, and it is busy" without a spinner. nanoMuse's answer is a red panda — small, red-brown, a ringed tail, cream cheeks, tear marks — drawn as an SVG so that it can be posed from the app's state instead of swapped between photographs.

| State | What the app knows | What the panda does |
|---|---|---|
| idle | nothing running | breathes; blinks every few seconds; glances left and right; an ear twitches; the tail swings |
| working | `status.state == "working"` | sits at a small laptop and types, head nodding, eyes on the screen |
| waiting | `status.state == "waiting"` — an approval card or a question is open | one paw up, a "!" bubble bobbing beside it, a small hop |
| happy | a run just went from working to idle (3 s) or you tapped it | a bounce, an open smile, two sparkles |
| error | a tool call failed or was refused (4 s) | a shake, brows down, a drop of sweat |
| sleepy | the app is loaded but the server is unreachable | eyes closed, slow breathing, three z's |

The moods come from `web/src/mood.ts`: the status gives the pose it holds; two moments the store records — `finishedAt`, `mishapAt` — colour it briefly. Motion is CSS keyframes on SVG groups; every part is positioned by coordinates so the transforms can be animated, and `transform-box: view-box` with an explicit origin keeps the pivots where they belong. `still` freezes it for lists and pickers; `prefers-reduced-motion` stops all of it.

The same drawing, reduced to the head, is the logo: `web/public/icon.svg` and the PWA icons, the README cover, and the Android adaptive launcher (a forest-green plate; a monochrome silhouette with the eyes and nose punched out for themed icons and the status bar). All of them are generated from one list of paths so they cannot drift apart.

## Colour and type, in numbers

| Token | Light | Dark |
|---|---|---|
| `bg` | `#fcfcfc` | `#181819` |
| `surface` | `#ffffff` | `#202022` |
| `surface-2` | `#f2f2f4` | `#2a2a2d` |
| `border` | `#e7e7ea` | `#333337` |
| `fg` | `#111112` | `#ffffff` |
| `muted` | `#6b6b71` | `#9d9da4` |
| `accent` | `#0064d4` | `#1793ff` |
| user bubble | `#d8e9ff` | `#1c3d66` |

The panda: fur `#d8632e`, deep fur `#bf4f23`, cream `#fff4e6`, markings `#2a1a14`, tear marks `#a8482a`, blush `#f4a0a0`; the plate behind it in the app `#dcebdc`, the logo plate `#2f7a5a`.

Figtree throughout, set with Tailwind's scale: 15 px in bubbles, 12–13 px for status lines and captions, 17–20 px semibold for titles.

## Where nanoMuse differs on purpose

- **The phone's screen is visible.** Muse never shows you a screenshot; nanoMuse's phone steps are rows in the chat (`phone_act: tap "发送" …`) and the finger overlay shows on the phone itself, because a user should be able to see what a hand on their phone is doing.
- **Approvals name the scope.** Muse asks yes / no; nanoMuse's card offers *once*, *this task*, *always* and lists the grants under *Permissions*, each with a revoke button.
- **Everything has a plain-text form.** The same agent runs in a terminal (`nanomuse chat`) with the same approvals, and every screen is backed by a documented REST + WebSocket API, so another front-end can drive it.
- **The mascot is a drawing, not a photograph.** It costs a few kilobytes, poses from state, and can be printed on a sticker.

## Sources

Meta's announcement ([about.fb.com, September 2026](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/)), the walkthrough and sizzle videos on that page, and the app screenshots published with it. CopilotKit's [OpenMuse](https://github.com/CopilotKit/openmuse) for the product designs of durable tasks, watches and ideas with evidence. Nothing from either is copied; this page records what was learned.
