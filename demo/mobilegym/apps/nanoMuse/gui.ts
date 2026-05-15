import PackageManagerService from '@/os/PackageManagerService';

/**
 * The simulated phone as a device nanoMuse can operate.
 *
 * The server asks for two things over the notification bridge's WebSocket (see
 * `nanomuse.phone.link` on the Python side): the current *screen* — which app is open and the
 * visible elements, each with an id, its text and its position — and one *action* — tap,
 * type, swipe, back, home, open an app. Both are answered from inside the simulator: the
 * screen is read off the DOM of the 360×800 phone (`#root`), and actions go through MobileGym's
 * own `__SIM_INPUT__` / `__OS__` runtime API, the same gestures its benchmark dispatches.
 *
 * Coordinates are phone coordinates (0…360 × 0…800), whatever the page scale; the conversion to
 * browser viewport pixels happens here.
 */

const PHONE_WIDTH = 360;
const PHONE_HEIGHT = 800;
const MAX_ELEMENTS = 150;
const MAX_TEXT = 200;
/** How long to let the UI settle after an action before reading the screen again. */
const SETTLE_MS = 650;

export interface ScreenElement {
  id: number;
  role: string;
  text: string;
  desc: string;
  bounds: [number, number, number, number];
  clickable: boolean;
  editable: boolean;
  scrollable: boolean;
  focused: boolean;
  checked: boolean | null;
  value: string;
}

export interface ScreenPayload {
  app: string;
  app_name: string;
  route: string;
  width: number;
  height: number;
  keyboard: boolean;
  elements: ScreenElement[];
  note?: string;
}

export interface ActParams {
  action: string;
  element?: number;
  x?: number;
  y?: number;
  direction?: 'up' | 'down' | 'left' | 'right';
  distance?: number;
  text?: string;
  clear?: boolean;
  submit?: boolean;
  app?: string;
  seconds?: number;
}

export interface ActResult {
  note: string;
  screen: ScreenPayload;
}

export interface AppInfo {
  id: string;
  name: string;
}

// MobileGym's runtime globals (declared loosely: the simulator owns their types).
interface SimInput {
  tap: (x: number, y: number) => void;
  doubleTap: (x: number, y: number) => void;
  longPress: (x: number, y: number, ms?: number) => Promise<void>;
  type: (text: string, opts?: { clear?: boolean; perCharMs?: number }) => Promise<void>;
  swipe: (start: { x: number; y: number }, end: { x: number; y: number }, opts?: { ms?: number }) => Promise<void>;
  back: () => void;
  home: () => void;
  recent: () => void;
  enter: () => void;
}
interface SimOs {
  getAppRoute?: () => { app: string | null; path: string } | null;
  launchApp?: (id: string) => void;
  openApp?: (id: string, path?: string) => void;
  goHome?: () => void;
  keyboard?: { isVisible?: () => boolean };
}

function simInput(): SimInput {
  const api = (window as unknown as { __SIM_INPUT__?: SimInput }).__SIM_INPUT__;
  if (!api) throw new Error('the simulator input API (__SIM_INPUT__) is not available');
  return api;
}
function simOs(): SimOs {
  return (window as unknown as { __OS__?: SimOs }).__OS__ ?? {};
}

/** Every installed app, as the agent may name it. */
export function installedApps(): AppInfo[] {
  try {
    return PackageManagerService.getInstalledPackages().map((m) => ({
      id: String(m.id),
      name: String(m.displayName || m.id),
    }));
  } catch {
    return [];
  }
}

/** The app id for a name the agent used (id, display name, alias, or a substring of one). */
export function resolveApp(wanted: string): string | null {
  const q = wanted.trim().toLowerCase();
  if (!q) return null;
  let packages: readonly { id: string; displayName: string; displayNameEn?: string; aliases?: string[] }[] = [];
  try {
    packages = PackageManagerService.getInstalledPackages() as typeof packages;
  } catch {
    return wanted;
  }
  const names = (p: (typeof packages)[number]) =>
    [p.id, p.displayName, p.displayNameEn ?? '', ...(p.aliases ?? [])].map((n) => String(n).toLowerCase());
  const exact = packages.find((p) => names(p).includes(q));
  if (exact) return String(exact.id);
  const partial = packages.find((p) => names(p).some((n) => n && (n.includes(q) || q.includes(n))));
  return partial ? String(partial.id) : null;
}

// ------------------------------------------------------------------ geometry

function phoneRoot(): HTMLElement {
  const root = document.getElementById('root');
  if (!root) throw new Error('the simulator root (#root) is not on the page');
  return root;
}

interface Frame {
  left: number;
  top: number;
  scale: number;
}

function frame(): Frame {
  const rect = phoneRoot().getBoundingClientRect();
  const scale = rect.width > 0 ? rect.width / PHONE_WIDTH : 1;
  return { left: rect.left, top: rect.top, scale };
}

/** Browser viewport pixels → phone coordinates. */
function toPhone(f: Frame, x: number, y: number): [number, number] {
  return [(x - f.left) / f.scale, (y - f.top) / f.scale];
}

/** Phone coordinates → browser viewport pixels (what `__SIM_INPUT__` wants). */
function toViewport(f: Frame, x: number, y: number): { x: number; y: number } {
  return { x: f.left + x * f.scale, y: f.top + y * f.scale };
}

// Apps with a designViewportWidth are drawn inside a wrapper with CSS `zoom`. Browsers before
// the standardised zoom (Chromium < 128) report getBoundingClientRect() in unzoomed units for
// everything inside such a wrapper, which puts the bottom of a WeChat page below the phone.
let rectsIgnoreZoom: boolean | null = null;

function probeZoom(): boolean {
  if (rectsIgnoreZoom !== null) return rectsIgnoreZoom;
  const probe = document.createElement('div');
  probe.style.cssText = 'position:absolute;left:0;top:0;width:100px;height:10px;zoom:0.5;visibility:hidden;pointer-events:none';
  document.body.appendChild(probe);
  rectsIgnoreZoom = Math.abs(probe.getBoundingClientRect().width - 100) < 1;
  probe.remove();
  return rectsIgnoreZoom;
}

/** The element's box in real viewport pixels, whatever the browser does with `zoom`. */
function visualRect(el: Element, root: Element, zoomOf: (el: Element) => number): DOMRect {
  const r = el.getBoundingClientRect();
  if (!probeZoom()) return r;
  let { left, top, right, bottom } = r;
  for (let a: Element | null = el; a && a !== root; a = a.parentElement) {
    const z = zoomOf(a);
    if (z === 1) continue;
    const o = a.getBoundingClientRect(); // its origin is real, its content is not
    left = o.left + (left - o.left) * z;
    right = o.left + (right - o.left) * z;
    top = o.top + (top - o.top) * z;
    bottom = o.top + (bottom - o.top) * z;
  }
  return new DOMRect(left, top, right - left, bottom - top);
}

// ------------------------------------------------------------------ reading the screen

const INTERACTIVE_TAGS = new Set(['BUTTON', 'A', 'INPUT', 'TEXTAREA', 'SELECT', 'SUMMARY']);
const INTERACTIVE_ROLES = new Set([
  'button',
  'link',
  'tab',
  'checkbox',
  'switch',
  'radio',
  'menuitem',
  'option',
  'textbox',
  'searchbox',
  'slider',
  'listitem',
]);
const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'SVG', 'PATH', 'NOSCRIPT', 'TEMPLATE', 'CANVAS', 'VIDEO', 'AUDIO']);

/** React attaches handlers as props on the DOM node; a clickable div shows up there. */
function hasReactHandler(el: Element): boolean {
  for (const key of Object.keys(el)) {
    if (key.startsWith('__reactProps')) {
      const props = (el as unknown as Record<string, Record<string, unknown>>)[key];
      return Boolean(
        props &&
          (props.onClick || props.onPointerDown || props.onPointerUp || props.onTouchStart || props.onMouseDown),
      );
    }
  }
  return false;
}

function isInteractive(el: Element, style: CSSStyleDeclaration): boolean {
  if (INTERACTIVE_TAGS.has(el.tagName)) return true;
  const role = el.getAttribute('role');
  if (role && INTERACTIVE_ROLES.has(role)) return true;
  if ((el as HTMLElement).isContentEditable) return true;
  if (el.hasAttribute('data-trigger') || el.hasAttribute('data-action')) return true;
  const tabindex = el.getAttribute('tabindex');
  if (tabindex !== null && Number(tabindex) >= 0) return true;
  // `cursor: pointer` is inherited: only the element that sets it is the clickable one
  if (style.cursor === 'pointer') {
    const parent = el.parentElement;
    if (!parent || getComputedStyle(parent).cursor !== 'pointer') return true;
  }
  return hasReactHandler(el);
}

function isScrollable(el: Element, style: CSSStyleDeclaration): boolean {
  if (el.hasAttribute('data-scroll-container')) return true;
  const oy = style.overflowY;
  const ox = style.overflowX;
  const scrollsY = (oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight + 4;
  const scrollsX = (ox === 'auto' || ox === 'scroll') && el.scrollWidth > el.clientWidth + 4;
  return scrollsY || scrollsX;
}

function ownText(el: Element): string {
  let text = '';
  for (const node of el.childNodes) {
    if (node.nodeType === Node.TEXT_NODE) text += node.textContent ?? '';
  }
  return collapse(text);
}

function collapse(text: string): string {
  const t = text.replace(/\s+/g, ' ').trim();
  return t.length > MAX_TEXT ? `${t.slice(0, MAX_TEXT - 1)}…` : t;
}

function roleOf(el: Element, interactive: boolean, scrollable: boolean): string {
  const tag = el.tagName;
  const aria = el.getAttribute('role');
  if (tag === 'INPUT') {
    const type = (el as HTMLInputElement).type;
    if (type === 'checkbox') return 'checkbox';
    if (type === 'radio') return 'radio';
    if (type === 'range') return 'slider';
    return 'input';
  }
  if (tag === 'TEXTAREA' || (el as HTMLElement).isContentEditable) return 'input';
  if (tag === 'SELECT') return 'select';
  if (tag === 'IMG') return 'image';
  if (aria && INTERACTIVE_ROLES.has(aria)) return aria;
  if (tag === 'A') return 'link';
  if (tag === 'BUTTON' || interactive) return 'button';
  if (scrollable) return 'list';
  if (/^H[1-6]$/.test(tag)) return 'heading';
  return 'text';
}

/**
 * MobileGym tags its controls with an action id such as `home.stationSelect.from`; the tail of
 * it says what an unlabelled control is for (from/to, swap, dateSelect) better than a position.
 */
function actionHint(el: Element): string {
  const id = el.getAttribute('data-action') ?? el.getAttribute('data-trigger') ?? '';
  if (!id || !/^[\w.-]+$/.test(id)) return '';
  const parts = id.split('.');
  return (parts.length >= 3 ? parts.slice(1) : parts).join('.');
}

/** "icon, top right" — for controls that have no text, named the way a person would. */
function positionHint(x1: number, y1: number, x2: number, y2: number): string {
  const w = x2 - x1;
  const h = y2 - y1;
  if (w >= PHONE_WIDTH * 0.9 && y1 <= 2 && h <= 56) return 'status bar';
  if (w >= PHONE_WIDTH * 0.9 && y2 >= PHONE_HEIGHT - 2 && h <= 40) return 'home gesture bar';
  if (w * h >= PHONE_WIDTH * PHONE_HEIGHT * 0.5) return 'page background';
  const cx = (x1 + x2) / 2;
  const cy = (y1 + y2) / 2;
  const row = cy < PHONE_HEIGHT / 3 ? 'top' : cy < (PHONE_HEIGHT * 2) / 3 ? 'middle' : 'bottom';
  const col = cx < PHONE_WIDTH / 3 ? 'left' : cx < (PHONE_WIDTH * 2) / 3 ? 'centre' : 'right';
  return `icon, ${row} ${col}`;
}

/** Is the element what a finger would hit (not hidden under a sheet, dialog or the keyboard)? */
function isOnTop(el: Element, left: number, top: number, right: number, bottom: number): boolean {
  const w = right - left;
  const h = bottom - top;
  // the centre first; a badge or icon sitting on the centre must not hide the whole thing
  const points: [number, number][] = [
    [left + w / 2, top + h / 2],
    [left + w * 0.25, top + h / 2],
    [left + w * 0.75, top + h / 2],
    [left + w / 2, top + h * 0.25],
    [left + w / 2, top + h * 0.75],
  ];
  for (const [x, y] of points) {
    const hit = document.elementFromPoint(x, y);
    if (hit && (hit === el || el.contains(hit) || hit.contains(el))) return true;
  }
  return false;
}

/** Read the phone's screen: the app and every visible element that a person could see or touch. */
export function readScreen(): ScreenPayload {
  const root = phoneRoot();
  const f = frame();
  const rootRect = root.getBoundingClientRect();
  const os = simOs();
  const route = os.getAppRoute?.() ?? null;
  const appId = route?.app ?? '';
  const apps = installedApps();
  const appName = appId ? apps.find((a) => a.id === appId)?.name ?? appId : 'Home';

  interface Candidate {
    el: Element;
    rect: DOMRect;
    interactive: boolean;
    scrollable: boolean;
    style: CSSStyleDeclaration;
  }
  const candidates: Candidate[] = [];
  const interactiveSet = new Set<Element>();
  const hasInteractiveInside = new Set<Element>();
  const zooms = new Map<Element, number>();
  const zoomOf = (el: Element): number => {
    let z = zooms.get(el);
    if (z === undefined) {
      z = Number.parseFloat(getComputedStyle(el).zoom || '1') || 1;
      zooms.set(el, z);
    }
    return z;
  };

  // the on-screen keyboard is one thing, not sixty buttons: it is listed once, below
  const keyboard: { el: Element | null } = { el: null };
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, {
    acceptNode: (n) => {
      if ((n as Element).hasAttribute('data-keyboard')) {
        keyboard.el = n as Element;
        return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  let node = walker.currentNode as Element | null;
  while (node) {
    const el = node;
    node = walker.nextNode() as Element | null;
    if (el === root || SKIP_TAGS.has(el.tagName)) continue;
    if (el.getAttribute('aria-hidden') === 'true') continue;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) continue;
    if (style.pointerEvents === 'none' && !ownText(el)) continue;
    zooms.set(el, Number.parseFloat(style.zoom || '1') || 1);
    const rect = visualRect(el, root, zoomOf);
    if (rect.width < 2 || rect.height < 2) continue;
    // inside the phone at all?
    if (rect.right <= rootRect.left || rect.left >= rootRect.right || rect.bottom <= rootRect.top || rect.top >= rootRect.bottom) continue;
    const interactive = isInteractive(el, style);
    const scrollable = isScrollable(el, style);
    const text = ownText(el);
    const isImage = el.tagName === 'IMG' && Boolean((el as HTMLImageElement).alt);
    if (!interactive && !scrollable && !text && !isImage) continue;
    if (interactive) {
      interactiveSet.add(el);
      for (let p = el.parentElement; p && p !== root; p = p.parentElement) hasInteractiveInside.add(p);
    }
    candidates.push({ el, rect, interactive, scrollable, style });
  }

  const elements: ScreenElement[] = [];
  for (const c of candidates) {
    const { el, rect } = c;
    // text inside a button belongs to the button: it is listed once, as the button's label
    // (text in a row that holds further controls stays, since the row does not repeat it)
    if (!c.interactive && !c.scrollable) {
      let p = el.parentElement;
      let owned = false;
      while (p && p !== root) {
        if (interactiveSet.has(p)) {
          owned = !hasInteractiveInside.has(p);
          break;
        }
        p = p.parentElement;
      }
      if (owned) continue;
    }
    // clip to the phone, then hit-test the visible centre
    const left = Math.max(rect.left, rootRect.left);
    const top = Math.max(rect.top, rootRect.top);
    const right = Math.min(rect.right, rootRect.right);
    const bottom = Math.min(rect.bottom, rootRect.bottom);
    if (right - left < 2 || bottom - top < 2) continue;
    if (!isOnTop(el, left, top, right, bottom)) continue;

    const [x1, y1] = toPhone(f, left, top);
    const [x2, y2] = toPhone(f, right, bottom);
    const html = el as HTMLElement;
    const input = el as HTMLInputElement;
    const isField = el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || html.isContentEditable;
    const editable = isField && !input.readOnly && !input.disabled;
    // a button's label is everything inside it; a container that holds other controls only
    // gets its own words, its children speak for themselves
    let text: string;
    if (!c.interactive) text = ownText(el);
    else if (!hasInteractiveInside.has(el)) text = collapse(html.innerText ?? '');
    else {
      const inner = collapse(html.innerText ?? '');
      text = ownText(el) || (inner.length <= 60 ? inner : '');
    }
    if (el.tagName === 'IMG') text = collapse((el as HTMLImageElement).alt);
    if (isField) text = '';
    let desc = collapse(
      el.getAttribute('aria-label') ??
        el.getAttribute('title') ??
        el.getAttribute('placeholder') ??
        (el as HTMLImageElement).alt ??
        actionHint(el),
    );
    // an unlabelled clickable wrapper inside another clickable (icon boxes, ripple layers) adds nothing
    if (c.interactive && !isField && !text && !desc) {
      let p = el.parentElement;
      let nested = false;
      while (p && p !== root) {
        if (interactiveSet.has(p)) {
          nested = true;
          break;
        }
        p = p.parentElement;
      }
      if (nested) continue;
      // an icon with no name: say where it sits, which is how a person would name it
      desc = positionHint(x1, y1, x2, y2);
    }
    let checked: boolean | null = null;
    if (el.tagName === 'INPUT' && (input.type === 'checkbox' || input.type === 'radio')) checked = input.checked;
    else if (el.getAttribute('aria-checked') !== null) checked = el.getAttribute('aria-checked') === 'true';
    else if (el.getAttribute('role') === 'switch') checked = el.getAttribute('aria-pressed') === 'true';
    const value =
      isField && checked === null ? collapse(html.isContentEditable ? html.innerText : input.value ?? '') : '';
    elements.push({
      id: 0,
      role: roleOf(el, c.interactive, c.scrollable),
      text,
      desc: desc === text ? '' : desc,
      bounds: [Math.round(x1), Math.round(y1), Math.round(x2), Math.round(y2)],
      clickable: c.interactive,
      editable,
      scrollable: c.scrollable,
      focused: document.activeElement === el,
      checked,
      value,
    });
  }

  if (keyboard.el) {
    const kr = visualRect(keyboard.el, root, zoomOf);
    const [kx1, ky1] = toPhone(f, Math.max(kr.left, rootRect.left), Math.max(kr.top, rootRect.top));
    const [kx2, ky2] = toPhone(f, Math.min(kr.right, rootRect.right), Math.min(kr.bottom, rootRect.bottom));
    elements.push({
      id: 0,
      role: 'keyboard',
      text: 'on-screen keyboard — use the type and enter actions, do not tap the keys',
      desc: '',
      bounds: [Math.round(kx1), Math.round(ky1), Math.round(kx2), Math.round(ky2)],
      clickable: false,
      editable: false,
      scrollable: false,
      focused: false,
      checked: null,
      value: '',
    });
  }

  // two boxes at the same place are one thing to a finger: keep the labelled one
  const seen = new Map<string, ScreenElement>();
  const unique: ScreenElement[] = [];
  for (const e of elements) {
    const key = e.bounds.join(',');
    const other = seen.get(key);
    if (!other) {
      seen.set(key, e);
      unique.push(e);
    } else if (!other.text && !other.desc && (e.text || e.desc)) {
      unique[unique.indexOf(other)] = e;
      seen.set(key, e);
    }
  }
  // reading order, then number them
  unique.sort((a, b) => a.bounds[1] - b.bounds[1] || a.bounds[0] - b.bounds[0]);
  const trimmed = unique.slice(0, MAX_ELEMENTS);
  trimmed.forEach((e, i) => {
    e.id = i + 1;
  });
  return {
    app: appId || 'launcher',
    app_name: appName,
    route: route?.path ?? '',
    width: PHONE_WIDTH,
    height: PHONE_HEIGHT,
    keyboard: Boolean(os.keyboard?.isVisible?.()),
    elements: trimmed,
    note: unique.length > MAX_ELEMENTS ? `${unique.length - MAX_ELEMENTS} more elements not listed` : undefined,
  };
}

// ------------------------------------------------------------------ acting

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function point(params: ActParams): { x: number; y: number } {
  if (typeof params.x === 'number' && typeof params.y === 'number') return { x: params.x, y: params.y };
  throw new Error(`\`${params.action}\` needs a point (the server resolves element ids to x/y)`);
}

/** One action, then the screen as it looks afterwards. */
export async function act(params: ActParams): Promise<ActResult> {
  const f = frame();
  const input = simInput();
  const os = simOs();
  let note = 'ok';
  switch (params.action) {
    case 'tap': {
      const p = toViewport(f, point(params).x, point(params).y);
      input.tap(p.x, p.y);
      break;
    }
    case 'double_tap': {
      const p = toViewport(f, point(params).x, point(params).y);
      input.doubleTap(p.x, p.y);
      break;
    }
    case 'long_press': {
      const p = toViewport(f, point(params).x, point(params).y);
      await input.longPress(p.x, p.y, 800);
      break;
    }
    case 'type': {
      if (typeof params.x === 'number' && typeof params.y === 'number') {
        // focus the field first, like a finger would
        const p = toViewport(f, params.x, params.y);
        input.tap(p.x, p.y);
        await sleep(120);
      }
      await input.type(String(params.text ?? ''), { clear: Boolean(params.clear), perCharMs: 8 });
      if (params.submit) {
        await sleep(80);
        input.enter();
      }
      break;
    }
    case 'swipe': {
      const dir = params.direction ?? 'up';
      const dist = Math.min(0.9, Math.max(0.1, params.distance ?? 0.5));
      const cx = typeof params.x === 'number' ? params.x : PHONE_WIDTH / 2;
      const cy = typeof params.y === 'number' ? params.y : PHONE_HEIGHT / 2;
      const dy = dir === 'up' || dir === 'down' ? dist * PHONE_HEIGHT : 0;
      const dx = dir === 'left' || dir === 'right' ? dist * PHONE_WIDTH : 0;
      const sign = dir === 'up' || dir === 'left' ? 1 : -1;
      const clampX = (v: number) => Math.min(PHONE_WIDTH - 8, Math.max(8, v));
      const clampY = (v: number) => Math.min(PHONE_HEIGHT - 8, Math.max(8, v));
      const start = toViewport(f, clampX(cx + (sign * dx) / 2), clampY(cy + (sign * dy) / 2));
      const end = toViewport(f, clampX(cx - (sign * dx) / 2), clampY(cy - (sign * dy) / 2));
      await input.swipe(start, end, { ms: 320 });
      break;
    }
    case 'enter':
      input.enter();
      break;
    case 'back':
      input.back();
      break;
    case 'home':
      input.home();
      break;
    case 'recents':
      input.recent();
      break;
    case 'open_app': {
      const id = resolveApp(String(params.app ?? ''));
      if (!id) throw new Error(`no app called '${params.app}' on this phone`);
      if (os.launchApp) os.launchApp(id);
      else if (os.openApp) os.openApp(id);
      else throw new Error('the simulator cannot open apps (__OS__.launchApp missing)');
      note = `opened ${id}`;
      await sleep(400);
      break;
    }
    case 'wait': {
      const seconds = Math.min(10, Math.max(0.2, Number(params.seconds ?? 1)));
      await sleep(seconds * 1000);
      note = `waited ${seconds}s`;
      break;
    }
    default:
      throw new Error(`unknown action '${params.action}'`);
  }
  await sleep(SETTLE_MS);
  return { note, screen: readScreen() };
}
