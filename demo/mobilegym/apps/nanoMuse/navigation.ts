import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { NAVIGATION_DECLARATION, type TransitionId } from './navigation.declaration';

/**
 * `go()` / `back()` for this app. Pages never touch react-router directly (see the platform's
 * app module contract); they call these with a transition id from the declaration.
 */
export function useAppNavigate() {
  const navigate = useNavigate();

  const go = useCallback(
    (id: TransitionId, params: Record<string, string> = {}, options?: { mode?: 'push' | 'replace' }) => {
      const t = NAVIGATION_DECLARATION.transitions.find((x) => x.id === id);
      if (!t) throw new Error(`Transition not found: ${id}`);
      const search = new URLSearchParams(params).toString();
      const target = search ? `${t.to}?${search}` : t.to;
      const mode = options?.mode ?? t.mode;
      navigate(target, mode === 'replace' ? { replace: true } : undefined);
    },
    [navigate],
  );

  const back = useCallback((steps = 1) => navigate(-steps), [navigate]);

  return { go, back };
}
