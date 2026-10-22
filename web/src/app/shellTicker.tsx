/* The top bar's live ticker slot. The shell always shows connection and sync;
 * a screen adds its own ambient status (weather, ACWR, triage) with
 * useShellTicker and, optionally, what the details button opens. */

import { createContext, useContext, useEffect } from "react";
import type { TickerItem } from "../components/motion.tsx";

export interface ShellTickerContribution {
  items: TickerItem[];
  onOpenDetails?: () => void;
  detailsLabel?: string;
}

export const ShellTickerContext = createContext<((next: ShellTickerContribution | null) => void) | null>(null);

/** Put this screen's items into the top bar ticker while it is mounted.
 *  Pass a memoised contribution (useMemo) so it is not re-sent each render. */
export function useShellTicker(contribution: ShellTickerContribution | null): void {
  const set = useContext(ShellTickerContext);
  useEffect(() => {
    if (!set) return;
    set(contribution);
    return () => set(null);
  }, [set, contribution]);
}
