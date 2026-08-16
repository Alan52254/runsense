import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Icon } from "../components/Icon.tsx";
import type { IconName } from "../components/Icon.tsx";
import { Avatar, Button, Modal, Field, Notice } from "../components/ui.tsx";
import { useAuth, DEMO_MFA_CODE } from "../state/AuthContext.tsx";
import type { Workspace } from "../state/AuthContext.tsx";
import { useWorkspace } from "../state/WorkspaceContext.tsx";
import { DEMO_TEAM_NAME } from "../data/demoData.ts";
import { apiConfigured } from "../data/apiClient.ts";

interface NavEntry {
  to: string;
  label: string;
  icon: IconName;
  end?: boolean;
}

const ATHLETE_NAV: { section: string; items: NavEntry[] }[] = [
  {
    section: "訓練",
    items: [
      { to: "/app", label: "今日總覽", icon: "home", end: true },
      { to: "/app/log", label: "記錄訓練", icon: "plus" },
      { to: "/app/history", label: "訓練紀錄", icon: "calendar" },
      { to: "/app/load", label: "訓練負荷", icon: "gauge" },
      { to: "/app/body", label: "身體狀況", icon: "heart" },
    ],
  },
  {
    section: "帳號",
    items: [
      { to: "/app/team", label: "團隊與授權", icon: "users" },
      { to: "/app/settings", label: "設定", icon: "settings" },
    ],
  },
];

const COACH_NAV: { section: string; items: NavEntry[] }[] = [
  {
    section: DEMO_TEAM_NAME,
    items: [
      { to: "/coach", label: "團隊總覽", icon: "users", end: true },
      { to: "/coach/assignments", label: "課表指派", icon: "calendar" },
    ],
  },
];

const PAGE_META: Record<string, { title: string; sub: string }> = {
  "/app": { title: "今日總覽", sub: "今天的課表、負荷趨勢與待辦" },
  "/app/log": { title: "記錄訓練", sub: "手動輸入一次訓練摘要" },
  "/app/history": { title: "訓練紀錄", sub: "所有紀錄與同步狀態" },
  "/app/load": { title: "訓練負荷", sub: "7 天／28 天負荷趨勢" },
  "/app/body": { title: "身體狀況", sub: "不適回報與分享範圍" },
  "/app/team": { title: "團隊與授權", sub: "邀請、成員關係與資料分享範圍" },
  "/app/settings": { title: "設定", sub: "個人資料、安全、隱私與整合" },
  "/coach": { title: "團隊總覽", sub: "依即時授權投影的選手狀態" },
  "/coach/assignments": { title: "課表指派", sub: "團隊擁有的課表資料" },
};

function pageMetaFor(pathname: string) {
  if (pathname.startsWith("/app/settings")) return PAGE_META["/app/settings"];
  if (pathname.startsWith("/coach/athletes"))
    return { title: "選手詳情", sub: "只顯示該選手目前授權的範圍" };
  return PAGE_META[pathname] ?? { title: "RunSense", sub: "" };
}

export function AppShell({ workspace }: { workspace: Workspace }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { auth, logout, enterWorkspace, satisfyMfa } = useAuth();
  const {
    preferences,
    setTheme,
    online,
    setOnline,
    syncNow,
    syncing,
    pendingCount,
    memberships,
  } = useWorkspace();

  const [menuOpen, setMenuOpen] = useState(false);
  const [mfaOpen, setMfaOpen] = useState(false);
  const [mfaCode, setMfaCode] = useState("");
  const [mfaError, setMfaError] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onClick(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [menuOpen]);

  if (!auth) return null;

  const nav = workspace === "athlete" ? ATHLETE_NAV : COACH_NAV;
  const meta = pageMetaFor(location.pathname);
  const invitationCount = memberships.filter((m) => m.status === "INVITED").length;

  function switchWorkspace(next: Workspace) {
    if (next === workspace) return;
    if (enterWorkspace(next)) {
      navigate(next === "athlete" ? "/app" : "/coach");
    } else {
      setMfaOpen(true);
    }
  }

  function submitMfa() {
    if (!satisfyMfa(mfaCode)) {
      setMfaError("驗證碼不正確");
      return;
    }
    setMfaOpen(false);
    setMfaCode("");
    setMfaError(null);
    navigate("/coach");
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="activity" size={17} strokeWidth={2} />
          </span>
          <span className="brand-name">RunSense</span>
          <span className="brand-phase">Phase 1A</span>
        </div>

        <div className="workspace-switch">
          <div className="segmented" style={{ width: "100%" }}>
            <button
              type="button"
              style={{ flex: 1 }}
              aria-pressed={workspace === "athlete"}
              onClick={() => switchWorkspace("athlete")}
            >
              選手
            </button>
            <button
              type="button"
              style={{ flex: 1 }}
              aria-pressed={workspace === "coach"}
              onClick={() => switchWorkspace("coach")}
            >
              教練
            </button>
          </div>
        </div>

        <nav className="nav">
          {nav.map((group) => (
            <div className="nav-section" key={group.section}>
              <div className="nav-section-label">{group.section}</div>
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    isActive ? "nav-item is-active" : "nav-item"
                  }
                >
                  <span className="nav-item-icon">
                    <Icon name={item.icon} size={17} />
                  </span>
                  {item.label}
                  {item.to === "/app/history" && pendingCount > 0 && (
                    <span className="nav-item-count">{pendingCount}</span>
                  )}
                  {item.to === "/app/team" && invitationCount > 0 && (
                    <span className="nav-item-count">{invitationCount}</span>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-foot" ref={menuRef} style={{ position: "relative" }}>
          {menuOpen && (
            <div
              className="card"
              style={{
                position: "absolute",
                bottom: "calc(100% - 4px)",
                left: 12,
                right: 12,
                boxShadow: "var(--shadow-lg)",
                padding: 6,
                zIndex: 20,
              }}
            >
              <button
                className="btn btn-ghost btn-sm"
                style={{ width: "100%", justifyContent: "flex-start" }}
                onClick={() => {
                  setTheme(preferences.theme === "dark" ? "light" : "dark");
                  setMenuOpen(false);
                }}
              >
                <Icon name={preferences.theme === "dark" ? "sun" : "moon"} size={15} />
                切換為{preferences.theme === "dark" ? "淺色" : "深色"}佈景
              </button>
              <button
                className="btn btn-ghost btn-sm"
                style={{ width: "100%", justifyContent: "flex-start" }}
                onClick={() => {
                  setMenuOpen(false);
                  navigate("/app/settings/security");
                }}
              >
                <Icon name="shield" size={15} />
                安全設定
              </button>
              <hr className="divider" style={{ margin: "5px 0" }} />
              <button
                className="btn btn-ghost btn-sm"
                style={{ width: "100%", justifyContent: "flex-start", color: "var(--critical)" }}
                onClick={() => {
                  logout();
                  navigate("/login");
                }}
              >
                <Icon name="logout" size={15} />
                登出
              </button>
            </div>
          )}

          <button className="account-button" onClick={() => setMenuOpen((v) => !v)}>
            <Avatar name={auth.athlete.name} />
            <span style={{ minWidth: 0 }}>
              <span className="account-name" style={{ display: "block" }}>
                {workspace === "coach" ? "教練視角" : auth.athlete.name}
              </span>
              <span className="account-mail" style={{ display: "block" }}>
                {auth.actor.email}
              </span>
            </span>
            <span style={{ marginLeft: "auto", color: "var(--text-muted)" }}>
              <Icon name="chevron-right" size={15} />
            </span>
          </button>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div>
            <div className="topbar-title">{meta.title}</div>
            {meta.sub && <div className="topbar-sub">{meta.sub}</div>}
          </div>

          <div className="topbar-actions">
            {workspace === "athlete" && (
              <>
                <button
                  className="conn-pill"
                  data-online={online}
                  onClick={() => setOnline(!online)}
                  title="示範用：切換連線狀態，觀察離線佇列行為"
                >
                  <span className="conn-dot" />
                  {online ? "已連線" : "離線模式"}
                </button>
                {pendingCount > 0 && (
                  <Button
                    size="sm"
                    variant="primary"
                    icon="refresh"
                    onClick={() => void syncNow()}
                    disabled={syncing || !online}
                  >
                    {syncing ? "同步中…" : `同步 ${pendingCount} 筆`}
                  </Button>
                )}
              </>
            )}
            <span className="req-tag">{apiConfigured ? "API 模式" : "示範資料模式"}</span>
          </div>
        </header>

        <main className="content">
          <div className="content-inner">
            <Outlet />
          </div>
        </main>
      </div>

      <Modal
        open={mfaOpen}
        title="切換教練視角需要 MFA"
        description="教練視角對應 head_coach 角色。角色被提升時必須立即完成多因素驗證，才能繼續操作。"
        onClose={() => setMfaOpen(false)}
        footer={
          <>
            <Button onClick={() => setMfaOpen(false)}>取消</Button>
            <Button variant="primary" onClick={submitMfa} disabled={mfaCode.length === 0}>
              驗證並切換
            </Button>
          </>
        }
      >
        <div className="stack">
          <Field
            label="驗證應用程式的 6 位數驗證碼"
            htmlFor="mfa-code"
            error={mfaError}
            hint={`示範環境固定為 ${DEMO_MFA_CODE}`}
          >
            <input
              id="mfa-code"
              className="input"
              inputMode="numeric"
              maxLength={6}
              value={mfaCode}
              placeholder="000000"
              onChange={(e) => {
                setMfaCode(e.target.value.replace(/\D/g, ""));
                setMfaError(null);
              }}
              onKeyDown={(e) => e.key === "Enter" && submitMfa()}
            />
          </Field>
          <Notice tone="neutral" icon="lock">
            這個示範用固定驗證碼取代真實 TOTP／Passkey，僅用於呈現流程。
          </Notice>
        </div>
      </Modal>
    </div>
  );
}
