import { useTriggerGestures } from '@/os/hooks/useTriggerGestures';
import type { TransitionId } from '../navigation.declaration';
import { useAppNavigate } from '../navigation';

/** Tap bindings that both navigate and tag the element with `data-trigger` for the analyzer. */
export function useOpenMuseGestures() {
  const { go, back } = useAppNavigate();
  const { bindTap } = useTriggerGestures<TransitionId>({
    execute: (id) => go(id),
  });
  return { bindTap, go, back };
}
