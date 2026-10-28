import { useEffect } from "react";
import type { RefObject } from "react";

/** A popover closes on a press outside it. */
export function useDismiss(open: boolean, scope: RefObject<HTMLElement | null>, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (scope.current && event.target instanceof Node && !scope.current.contains(event.target)) onClose();
    };
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open, scope, onClose]);
}

/** Put on the popover's wrapper: Esc closes it and nothing behind it (a drawer
 *  around it stays open), and focus goes back to the opener. */
export function escapeClose(onClose: () => void, restore?: RefObject<HTMLElement | null>) {
  return (event: { key: string; preventDefault: () => void; nativeEvent: Event }) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.nativeEvent.stopPropagation();
    onClose();
    restore?.current?.focus();
  };
}
