import PackageManagerService from '@/os/PackageManagerService';
import { domToPng } from 'modern-screenshot';

/**
 * The simulated phone as a device nanoMuse can operate.
 *
 * The server asks for two things over the notification bridge's WebSocket (see
 * `nanomuse.phone.link` on the Python side): the current *screen* — a screenshot, which app is
 * open, the screen size, whether the keyboard is up — and one *action* — tap, type, swipe, back,
 * home, open an app — by coordinates. That is the same contract the Android app fulfils with
 * `AccessibilityService.takeScreenshot()` and `dispatchGesture()`: no element tree on either,
 * because a real phone cannot be relied on to have one (WebViews, Flutter, games, protected
 * screens). The model looks at the picture and taps where a person would.
 *
 * The screenshot is rendered in the tab from the phone's DOM (`#root`, 360×800) with
 * modern-screenshot — MobileGym has no screenshot facility of its own — and actions go through
 * MobileGym's `__SIM_INPUT__` / `__OS__` runtime API, the same gestures its benchmark dispatches,
 * so a tap lands the way a finger would and the apps animate as they do for a person. A small
 * overlay shows where the finger went and what the agent is doing; it is not in the screenshot.
 *
 * Coordinates are phone coordinates (0…360 × 0…800), whatever the page scale; the conversion to
 * browser viewport pixels happens here.
 */

const PHONE_WIDTH = 360;
const PHONE_HEIGHT = 800;
/** Rendered pixels per phone pixel in the screenshot: 1 keeps it at 360×800 (~280 image tokens). */
const SHOT_SCALE = 1;
/** How long to let the UI settle after an action before reading the screen again. */
const SETTLE_MS = 650;
/** Timing that looks like a person, not a script (MobileGym's benchmark uses the same ranges). */
const TAP_GAP_MS = 120;
const TYPE_MS_PER_CHAR = 40;
const SWIPE_MS = 320;

export interface ScreenPayload {
  app: string;
  app_name: string;
  route: string;
  width: number;
  height: number;
  keyboard: boolean;
  /** base64 PNG of the phone, `width`×`height` × SHOT_SCALE */
  screenshot: string | null;
  note?: string;
}

export interface ActParams {
  action: string;
  x?: number;
  y?: number;
  x2?: number;
  y2?: number;
  label?: string;
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
  swipe: (
    start: { x: number; y: number },
    end: { x: number; y: number },
    opts?: { ms?: number; steps?: number; inertia?: boolean },
  ) => Promise<void>;
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

/** Phone coordinates → browser viewport pixels (what `__SIM_INPUT__` wants). */
function toViewport(f: Frame, x: number, y: number): { x: number; y: number } {
  return { x: f.left + x * f.scale, y: f.top + y * f.scale };
}

const clampX = (v: number) => Math.min(PHONE_WIDTH - 1, Math.max(0, v));
const clampY = (v: number) => Math.min(PHONE_HEIGHT - 1, Math.max(0, v));

// ------------------------------------------------------------------ the screenshot

const OVERLAY_ATTR = 'data-muse-overlay';

/**
 * Render the phone to a PNG. `#root` carries the page's `transform: scale(...)`, which the
 * clone must not (the picture is the phone at its own 360×800); the agent's overlay is left out.
 */
export async function screenshot(): Promise<string | null> {
  const root = phoneRoot();
  const rootRect = root.getBoundingClientRect();
  // Only what is inside the phone gets cloned: a station list or a chat history has thousands
  // of nodes scrolled out of view, and copying their styles is what makes a capture slow.
  const visible = (node: Node): boolean => {
    if (!(node instanceof Element)) return true;
    if (node.hasAttribute(OVERLAY_ATTR)) return false;
    if (node === root || node.tagName === 'HEAD' || node.tagName === 'STYLE') return true;
    const r = node.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return true; // display:contents, inline wrappers, svg defs
    return r.right > rootRect.left && r.left < rootRect.right && r.bottom > rootRect.top && r.top < rootRect.bottom;
  };
  try {
    const started = performance.now();
    const dataUrl = await domToPng(root, {
      width: PHONE_WIDTH,
      height: PHONE_HEIGHT,
      scale: SHOT_SCALE,
      backgroundColor: '#000',
      style: { transform: 'none', transition: 'none', margin: '0', inset: 'auto', position: 'static' },
      filter: visible,
      // fonts are the page's own; the SVG cannot see them unless embedded
      timeout: 8000,
    });
    lastCaptureMs = Math.round(performance.now() - started);
    const comma = dataUrl.indexOf(',');
    return comma >= 0 ? dataUrl.slice(comma + 1) : null;
  } catch (err) {
    console.warn('[nanoMuse] screenshot failed', err);
    return null;
  }
}

/** How long the last capture took, for the console and the tests. */
export let lastCaptureMs = 0;

/** Read the phone's screen: the picture, and the little the simulator can say about it. */
export async function readScreen(): Promise<ScreenPayload> {
  const os = simOs();
  const route = os.getAppRoute?.() ?? null;
  const appId = route?.app ?? '';
  const apps = installedApps();
  const appName = appId ? apps.find((a) => a.id === appId)?.name ?? appId : 'Home';
  const shot = await screenshot();
  return {
    app: appId || 'launcher',
    app_name: appName,
    route: route?.path ?? '',
    width: PHONE_WIDTH,
    height: PHONE_HEIGHT,
    keyboard: Boolean(os.keyboard?.isVisible?.()),
    screenshot: shot,
    note: shot ? undefined : 'the screenshot could not be rendered',
  };
}

// ------------------------------------------------------------------ the overlay

/**
 * What a person watching sees of the agent's hands: a ripple where it taps, a trail where it
 * swipes, a caption saying what it is doing. Lives inside `#root` so it scales with the phone;
 * `pointer-events: none` so it never gets in the way of the gestures themselves.
 */
class TouchIndicator {
  private layer: HTMLDivElement | null = null;
  private caption: HTMLDivElement | null = null;
  private captionTimer: ReturnType<typeof setTimeout> | null = null;

  private ensure(): HTMLDivElement {
    if (this.layer && this.layer.isConnected) return this.layer;
    const layer = document.createElement('div');
    layer.setAttribute(OVERLAY_ATTR, '');
    layer.style.cssText =
      'position:absolute;inset:0;z-index:2147483000;pointer-events:none;overflow:hidden;' +
      'font:12px/1.35 system-ui,-apple-system,"PingFang SC","Noto Sans CJK SC",sans-serif;';
    if (!document.getElementById('muse-overlay-style')) {
      const style = document.createElement('style');
      style.id = 'muse-overlay-style';
      style.textContent =
        '@keyframes muse-ripple{0%{transform:translate(-50%,-50%) scale(.35);opacity:.9}' +
        '100%{transform:translate(-50%,-50%) scale(1.6);opacity:0}}' +
        '@keyframes muse-hold{0%{transform:translate(-50%,-50%) scale(.5);opacity:.85}' +
        '100%{transform:translate(-50%,-50%) scale(1);opacity:.85}}' +
        '@keyframes muse-fade{0%{opacity:1}100%{opacity:0}}' +
        '@keyframes muse-caption{0%{opacity:0;transform:translateY(6px)}100%{opacity:1;transform:none}}';
      document.head.appendChild(style);
    }
    phoneRoot().appendChild(layer);
    this.layer = layer;
    return layer;
  }

  /** A ring that grows and fades where the finger came down. */
  ripple(x: number, y: number, holdMs = 0): void {
    const layer = this.ensure();
    const dot = document.createElement('div');
    const size = 44;
    dot.style.cssText =
      `position:absolute;left:${x}px;top:${y}px;width:${size}px;height:${size}px;border-radius:50%;` +
      'background:rgba(255,92,72,.28);border:2.5px solid rgba(255,92,72,.95);' +
      'box-shadow:0 0 0 2px rgba(255,255,255,.7);' +
      (holdMs > 0
        ? `animation:muse-hold ${holdMs}ms ease-out forwards, muse-fade 300ms ease-out ${holdMs}ms forwards;`
        : 'animation:muse-ripple 520ms ease-out forwards;');
    layer.appendChild(dot);
    setTimeout(() => dot.remove(), holdMs + 600);
  }

  /** A line from where the finger started to where it let go, drawn as it moves. */
  trail(x1: number, y1: number, x2: number, y2: number, ms: number): void {
    const layer = this.ensure();
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 ${PHONE_WIDTH} ${PHONE_HEIGHT}`);
    svg.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;';
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', String(x1));
    line.setAttribute('y1', String(y1));
    line.setAttribute('x2', String(x2));
    line.setAttribute('y2', String(y2));
    line.setAttribute('stroke', 'rgba(255,92,72,.9)');
    line.setAttribute('stroke-width', '4');
    line.setAttribute('stroke-linecap', 'round');
    const length = Math.hypot(x2 - x1, y2 - y1);
    line.setAttribute('stroke-dasharray', String(length));
    line.setAttribute('stroke-dashoffset', String(length));
    line.style.transition = `stroke-dashoffset ${ms}ms ease-out`;
    svg.appendChild(line);
    layer.appendChild(svg);
    requestAnimationFrame(() => {
      line.setAttribute('stroke-dashoffset', '0');
    });
    this.ripple(x1, y1);
    setTimeout(() => this.ripple(x2, y2), ms);
    svg.style.animation = `muse-fade 300ms ease-out ${ms + 250}ms forwards`;
    setTimeout(() => svg.remove(), ms + 600);
  }

  /** One line at the bottom of the phone: what the agent is doing right now. */
  say(text: string, ms = 2600): void {
    const layer = this.ensure();
    if (!this.caption || !this.caption.isConnected) {
      const cap = document.createElement('div');
      cap.style.cssText =
        'position:absolute;left:14px;right:14px;bottom:52px;padding:8px 12px;border-radius:14px;' +
        'background:rgba(20,20,24,.82);color:#fff;text-align:center;backdrop-filter:blur(6px);' +
        'animation:muse-caption 180ms ease-out;';
      layer.appendChild(cap);
      this.caption = cap;
    }
    this.caption.textContent = text;
    this.caption.style.opacity = '1';
    if (this.captionTimer) clearTimeout(this.captionTimer);
    this.captionTimer = setTimeout(() => {
      if (this.caption) this.caption.style.opacity = '0';
    }, ms);
  }
}

export const indicator = new TouchIndicator();

// ------------------------------------------------------------------ acting

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function point(params: ActParams): { x: number; y: number } {
  if (typeof params.x === 'number' && typeof params.y === 'number') {
    return { x: clampX(params.x), y: clampY(params.y) };
  }
  throw new Error(`\`${params.action}\` needs x and y`);
}

const ACTION_WORDS: Record<string, string> = {
  tap: '点击',
  double_tap: '双击',
  long_press: '长按',
  swipe: '滑动',
  type: '输入',
  enter: '回车',
  back: '返回',
  home: '回到桌面',
  recents: '最近任务',
  open_app: '打开',
  wait: '等待',
};

function caption(params: ActParams): string {
  const what = params.label?.trim();
  if (what) return `Muse · ${what}`;
  const word = ACTION_WORDS[params.action] ?? params.action;
  if (params.action === 'type') return `Muse · 输入 “${String(params.text ?? '').slice(0, 24)}”`;
  if (params.action === 'open_app') return `Muse · 打开 ${params.app ?? ''}`;
  if (params.action === 'swipe' && params.direction) return `Muse · 滑动 ${params.direction}`;
  return `Muse · ${word}`;
}

/** One action, then the screen as it looks afterwards. */
export async function act(params: ActParams): Promise<ActResult> {
  const f = frame();
  const input = simInput();
  const os = simOs();
  let note = 'ok';
  indicator.say(caption(params));
  switch (params.action) {
    case 'tap': {
      const p = point(params);
      indicator.ripple(p.x, p.y);
      const v = toViewport(f, p.x, p.y);
      input.tap(v.x, v.y);
      break;
    }
    case 'double_tap': {
      const p = point(params);
      indicator.ripple(p.x, p.y);
      const v = toViewport(f, p.x, p.y);
      input.doubleTap(v.x, v.y);
      break;
    }
    case 'long_press': {
      const p = point(params);
      const ms = Math.round(Math.min(5, Math.max(0.4, Number(params.seconds ?? 0.8))) * 1000);
      indicator.ripple(p.x, p.y, ms);
      const v = toViewport(f, p.x, p.y);
      await input.longPress(v.x, v.y, ms);
      break;
    }
    case 'type': {
      if (typeof params.x === 'number' && typeof params.y === 'number') {
        // focus the field first, like a finger would
        const p = point(params);
        indicator.ripple(p.x, p.y);
        const v = toViewport(f, p.x, p.y);
        input.tap(v.x, v.y);
        await sleep(TAP_GAP_MS);
      }
      await input.type(String(params.text ?? ''), { clear: Boolean(params.clear), perCharMs: TYPE_MS_PER_CHAR });
      if (params.submit) {
        await sleep(TAP_GAP_MS);
        input.enter();
      }
      break;
    }
    case 'swipe': {
      let start: { x: number; y: number };
      let end: { x: number; y: number };
      if (typeof params.x2 === 'number' && typeof params.y2 === 'number') {
        start = point(params);
        end = { x: clampX(params.x2), y: clampY(params.y2) };
      } else {
        const dir = params.direction ?? 'up';
        const dist = Math.min(0.9, Math.max(0.1, params.distance ?? 0.5));
        const cx = typeof params.x === 'number' ? params.x : PHONE_WIDTH / 2;
        const cy = typeof params.y === 'number' ? params.y : PHONE_HEIGHT / 2;
        const dy = dir === 'up' || dir === 'down' ? dist * PHONE_HEIGHT : 0;
        const dx = dir === 'left' || dir === 'right' ? dist * PHONE_WIDTH : 0;
        const sign = dir === 'up' || dir === 'left' ? 1 : -1;
        const edge = (v: number, max: number) => Math.min(max - 8, Math.max(8, v));
        start = { x: edge(cx + (sign * dx) / 2, PHONE_WIDTH), y: edge(cy + (sign * dy) / 2, PHONE_HEIGHT) };
        end = { x: edge(cx - (sign * dx) / 2, PHONE_WIDTH), y: edge(cy - (sign * dy) / 2, PHONE_HEIGHT) };
      }
      indicator.trail(start.x, start.y, end.x, end.y, SWIPE_MS);
      await input.swipe(toViewport(f, start.x, start.y), toViewport(f, end.x, end.y), { ms: SWIPE_MS, inertia: true });
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
  return { note, screen: await readScreen() };
}

// A handle for the console and for tests, the way MobileGym exposes __SIM_INPUT__ / __OS__.
(window as unknown as { __MUSE_GUI__?: unknown }).__MUSE_GUI__ = {
  readScreen,
  act,
  screenshot,
  captureMs: () => lastCaptureMs,
};
