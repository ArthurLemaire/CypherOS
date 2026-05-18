import type { NavigationDeclaration } from './navigation.types';

const MAIN_SCROLL = [{ name: 'main', direction: 'vertical', description: 'Main content' }] as const;

export const NAVIGATION_DECLARATION = {
  app: 'nanomuse',
  routes: [
    {
      path: '/',
      component: 'MusePage',
      params: {},
      entryPoint: 'home',
      scrollContainers: MAIN_SCROLL,
      uiStates: [
        { id: 'nanomuse.muse.base', search: {}, description: 'The nanoMuse app (chat, feed, goals…)' },
        { id: 'nanomuse.muse.thread', search: { thread: '*' }, description: 'A specific chat' },
        { id: 'nanomuse.muse.tab', search: { tab: '*' }, description: 'A specific tab' },
      ],
      queryParams: { thread: 'string', tab: 'string' },
      description: 'nanoMuse, full screen',
    },
    {
      path: '/setup',
      component: 'SetupPage',
      params: {},
      entryPoint: 'none',
      scrollContainers: MAIN_SCROLL,
      uiStates: [{ id: 'nanomuse.setup.base', search: {}, description: 'Connect to an nanoMuse server' }],
      queryParams: {},
      description: 'Server address and access token',
    },
  ],
  transitions: [
    {
      id: 'muse.open',
      from: '*',
      to: '/',
      search: {},
      searchParams: {},
      mode: 'replace',
      params: {},
      label: 'Show nanoMuse',
      ui: { placement: 'none', icon: 'home', gesture: 'tap' },
    },
    {
      id: 'setup.open',
      from: '*',
      to: '/setup',
      search: {},
      searchParams: {},
      mode: 'push',
      params: {},
      label: 'Change the server nanoMuse connects to',
      ui: { placement: 'content', icon: 'settings', gesture: 'tap' },
    },
  ],
  capabilities: {
    historyBack: true,
  },
} as const satisfies NavigationDeclaration;

export type TransitionId = (typeof NAVIGATION_DECLARATION.transitions)[number]['id'];
