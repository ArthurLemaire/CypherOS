import type { AppManifest } from '@/os/types/manifest';
import { IcLauncher } from './res/icons';

/**
 * OpenMuse as an app on the simulated phone.
 *
 * The app is a thin shell: it shows the OpenMuse web app (served by `openmuse serve` on the
 * host) full-screen, and mirrors what the server wants from you — approvals, questions,
 * background results — into the simulator's notification shade.
 */
export const manifest: AppManifest = {
  id: 'openmuse',
  packageName: 'org.openmuse.app',
  displayName: 'OpenMuse',
  displayNameEn: 'OpenMuse',
  aliases: ['muse', 'open muse', 'personal agent', 'assistant'],
  version: '0.2.0',
  versionCode: 2,
  type: 'plugin',
  icon: IcLauncher,
  iconBackground: 'linear-gradient(135deg, #6d28d9 0%, #a855f7 100%)',
  iconForeground: '#ffffff',
  designViewportWidth: 360,
  theme: {
    colors: {
      primary: '#7c3aed',
      primaryDark: '#6d28d9',
      onPrimary: '#ffffff',
      accent: '#a855f7',
      background: '#f7f6fb',
      surface: '#ffffff',
      textPrimary: '#1b1730',
      textSecondary: '#6b6880',
      border: '#e6e3f0',
      statusBarForeground: 'dark',
      navigationBarForeground: 'dark',
    },
    colorsDark: {
      primary: '#a78bfa',
      primaryDark: '#8b5cf6',
      onPrimary: '#1b1730',
      accent: '#c4b5fd',
      background: '#121019',
      surface: '#1c1926',
      textPrimary: '#f3f1fa',
      textSecondary: '#a09cb3',
      border: '#2a2637',
      statusBarForeground: 'light',
      navigationBarForeground: 'light',
    },
  },
  splash: { kind: 'branded', tagline: 'Your Muse, on this phone', minDurationMs: 400 },
};
