import { useCallback, type CSSProperties } from 'react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { useAppNavigationHandler } from '@/os/hooks/useAppNavigationHandler';
import { useDarkMode } from '@/os/hooks/useDarkMode';
import { applySkinToThemeColors } from '@/os/SkinService';
import { themeToCssVars } from '@/os/utils/themeToCssVars';
import { manifest } from './manifest';
import { useAppNavigate } from './navigation';
import { useOpenMuseStore } from './state';
import MusePage from './pages/MusePage';
import SetupPage from './pages/SetupPage';

function NavigationHandler() {
  const location = useLocation();
  const { back } = useAppNavigate();
  const configured = useOpenMuseStore((s) => !!s.serverUrl);

  const onBack = useCallback((): boolean => {
    // setup reached from the app: back returns to the app; setup on first launch: back leaves
    if (location.pathname === '/setup' && configured) {
      back();
      return true;
    }
    return false;
  }, [location.pathname, configured, back]);

  useAppNavigationHandler(manifest.id, {
    onBack,
    // notifications open the app with "/?thread=<id>"; the OS hands us that path verbatim
    onNavigate: (path, navigateToPath) => navigateToPath(path.startsWith('/') ? path : `/${path}`),
  });

  return null;
}

function AppInner() {
  return (
    <>
      <NavigationHandler />
      <Routes>
        <Route path="/" element={<MusePage />} />
        <Route path="/setup" element={<SetupPage />} />
      </Routes>
    </>
  );
}

export default function OpenMuseApp() {
  const { isDark } = useDarkMode();
  const colors = isDark ? { ...manifest.theme.colors, ...(manifest.theme.colorsDark ?? {}) } : manifest.theme.colors;
  const cssVars = themeToCssVars(applySkinToThemeColors(colors)) as CSSProperties;
  return (
    <div className="h-full w-full" style={cssVars}>
      <MemoryRouter>
        <AppInner />
      </MemoryRouter>
    </div>
  );
}
