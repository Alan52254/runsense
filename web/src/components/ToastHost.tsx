import { useToast } from "../state/ToastContext.tsx";
import { Icon } from "./Icon.tsx";

export function ToastHost() {
  const { toasts, dismiss } = useToast();
  if (toasts.length === 0) return null;

  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast-${toast.tone}`}>
          <div className="row-between" style={{ alignItems: "flex-start" }}>
            <div>
              <div className="toast-title">{toast.title}</div>
              {toast.detail && <div className="toast-detail">{toast.detail}</div>}
            </div>
            <button
              className="btn btn-ghost btn-sm btn-icon"
              onClick={() => dismiss(toast.id)}
              aria-label="關閉通知"
            >
              <Icon name="x" size={14} />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
