import { useCallback, useEffect, useId, useRef, useState } from "react";
import { DotsThree } from "@phosphor-icons/react";
import { roveIndex } from "../lib/coachChatUi.ts";
import type { CoachTab } from "../state/CoachChatContext.tsx";
import { escapeClose, useDismiss } from "./useDismiss.ts";

/** Where in the coach you are: 問教練, 身體回報 or 專業指引. A small menu in
 *  the header instead of a tab strip beside the thread. */
export function CoachMenu({
  items,
  active,
  onSelect,
  label,
}: {
  items: { id: CoachTab; label: string }[];
  active: CoachTab;
  onSelect: (tab: CoachTab) => void;
  label: string;
}) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const scope = useRef<HTMLDivElement | null>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, scope, close);

  useEffect(() => {
    if (open) itemRefs.current[Math.max(0, items.findIndex((item) => item.id === active))]?.focus();
  }, [open, items, active]);

  return (
    <div className="cc-menu" ref={scope} onKeyDown={escapeClose(close, opener)}>
      <button
        ref={opener}
        type="button"
        className="btn btn-ghost cc-menu-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        aria-label={label}
        onClick={() => setOpen((value) => !value)}
      >
        <DotsThree size={22} weight="bold" aria-hidden="true" />
      </button>
      {open && (
        <div className="cc-menu-pop" id={menuId} role="menu" aria-label={label}>
          {items.map((item, index) => (
            <button
              key={item.id}
              ref={(el) => {
                itemRefs.current[index] = el;
              }}
              type="button"
              role="menuitemradio"
              aria-checked={active === item.id}
              className="cc-menu-item"
              onKeyDown={(event) => {
                const next = roveIndex(items.length, index, event.key);
                if (next === null) return;
                event.preventDefault();
                itemRefs.current[next]?.focus();
              }}
              onClick={() => {
                onSelect(item.id);
                close();
                opener.current?.focus();
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
