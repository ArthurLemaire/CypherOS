import type { NavigationDeclaration } from './navigation.types';

const MAIN_SCROLL = [{ name: 'main', direction: 'vertical', description: 'Main content' }] as const;

export const NAVIGATION_DECLARATION = {
  app: 'openmuse',
  routes: [
    {
      path: '/',
      component: 'MusePage',
      params: {},
      entryPoint: 'home',
      scrollContainers: MAIN_SCROLL,
      uiStates: [
        { id: 'openmuse.muse.base', search: {}, description: 'The OpenMuse app (chat, feed, goals…)' },
        { id: 'openmuse.muse.thread', search: { thread: '*' }, description: 'A specific chat' },
        { id: 'openmuse.muse.tab', search: { tab: '*' }, description: 'A specific tab' },
      ],
      queryParams: { thread: 'string', tab: 'string' },
      description: 'OpenMuse, full screen',
    },
    {
      path: '/setup',
      component: 'SetupPage',
      params: {},
      entryPoint: 'none',
      scrollContainers: MAIN_SCROLL,
      uiStates: [{ id: 'openmuse.setup.base', search: {}, description: 'Connect to an OpenMuse server' }],
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
      label: 'Show OpenMuse',
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
      label: 'Change the server OpenMuse connects to',
      ui: { placement: 'content', icon: 'settings', gesture: 'tap' },
    },
  ],
  capabilities: {
    historyBack: true,
  },
} as const satisfies NavigationDeclaration;

export type TransitionId = (typeof NAVIGATION_DECLARATION.transitions)[number]['id'];
