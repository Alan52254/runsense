import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Icon } from "../components/Icon.tsx";
import type { IconName } from "../components/Icon.tsx";
import { Avatar, Button, Modal, Field, Notice } from "../components/ui.tsx";
import { OtpInput } from "../components/OtpInput.tsx";
import { useAuth, DEMO_MFA_CODE } from "../state/AuthContext.tsx";
import type { Workspace } from "../state/AuthContext.tsx";
import { useWorkspace } from "../state/WorkspaceContext.tsx";
import { apiConfigured } from "../data/apiClient.ts";
import { useLocale } from "../state/LocaleContext.tsx";
import type { MessageKey } from "../state/LocaleContext.tsx";

interface NavEntry {
  to: string;
  label: MessageKey;
  icon: IconName;
  end?: boolean;
}

const ATHLETE_NAV: { section: MessageKey; items: NavEntry[] }[] = [
  {
    section: "training",
    items: [
      { to: "/app", label: "dashboard", icon: "home", end: true },
      { to: "/app/run", label: "liveRun", icon: "runner" },
      { to: "/app/log", label: "log", icon: "shoe" },
      { to: "/app/history", label: "history", icon: "history" },
      { to: "/app/load", label: "load", icon: "trend" },
      { to: "/app/body", label: "body", icon: "body-status" },
    ],
  },
  {
    section: "account",
    items: [
      { to: "/app/team", label: "team", icon: "users" },
      { to: "/app/settings", label: "settings", icon: "settings" },
    ],
  },
];

const COACH_NAV: { section: MessageKey; items: NavEntry[] }[] = [
  {
    section: "teamName",
    items: [
      { to: "/coach", label: "teamOverview", icon: "users", end: true },
      { to: "/coach/assignments", label: "assignments", icon: "assignment" },
    ],
  },
];

const PAGE_META: Record<string, { title: MessageKey; sub: MessageKey }> = {
  "/app": { title: "dashboard", sub: "dashboardMeta" },
  "/app/run": { title: "liveRun", sub: "liveRunMeta" },
  "/app/log": { title: "log", sub: "logMeta" },
  "/app/history": { title: "history", sub: "historyMeta" },
  "/app/load": { title: "load", sub: "loadMeta" },
  "/app/body": { title: "body", sub: "bodyMeta" },
  "/app/team": { title: "team", sub: "teamMeta" },
  "/app/settings": { title: "settings", sub: "settingsMeta" },
  "/coach": { title: "teamOverview", sub: "teamOverviewMeta" },
  "/coach/assignments": { title: "assignments", sub: "assignmentsMeta" },
};

const MOBILE_MORE_CAPTION: Record<string, MessageKey> = {
  "/app/load": "moreLoad",
  "/app/body": "moreBody",
  "/app/team": "moreTeam",
  "/app/settings": "moreSettings",
};

function pageMetaFor(pathname: string): { title: MessageKey | "RunSense"; sub: MessageKey | "" } {
  if (pathname.startsWith("/app/settings")) return PAGE_META["/app/settings"];
  if (pathname.startsWith("/coach/athletes"))
    return { title: "athleteDetail", sub: "athleteDetailMeta" };
  return PAGE_META[pathname] ?? { title: "RunSense", sub: "" };
}

export function AppShell({ workspace }: { workspace: Workspace }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { auth, logout, enterWorkspace, satisfyMfa } = useAuth();
  const { locale, setLocale, t } = useLocale();
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
  const [mobileMoreOpen, setMobileMoreOpen] = useState(false);
  const [mfaOpen, setMfaOpen] = useState(false);
  const [mfaCode, setMfaCode] = useState("");
  const [mfaError, setMfaError] = useState<string | null>(null);
  const [mfaSubmitting, setMfaSubmitting] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const accountButtonRef = useRef<HTMLButtonElement | null>(null);
  const contentRef = useRef<HTMLElement | null>(null);

  // .content (not window) is the actual scroll container -- a route change
  // otherwise leaves it wherever the previous page's scroll happened to be.
  // useLayoutEffect (not useEffect) so this runs before the browser paints
  // the new route's content -- otherwise the old scroll position flashes
  // on screen for one frame before snapping back to the top.
  useLayoutEffect(() => {
    contentRef.current?.scrollTo(0, 0);
  }, [location.pathname]);

  useEffect(() => {
    if (!menuOpen) return;
    function onClick(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMenuOpen(false);
        accountButtonRef.current?.focus();
      }
    }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);

  if (!auth) return null;

  const nav = workspace === "athlete" ? ATHLETE_NAV : COACH_NAV;
  const mobileNav =
    workspace === "athlete" ? (nav[0]?.items.slice(0, 4) ?? []) : (nav[0]?.items ?? []);
  const mobileMoreItems =
    workspace === "athlete" ? (nav[0]?.items.slice(4) ?? []).concat(ATHLETE_NAV[1].items) : [];
  const mobileMoreActive = mobileMoreItems.some((item) =>
    location.pathname.startsWith(item.to),
  );
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

  async function submitMfa(overrideCode?: string) {
    const testCode = (overrideCode ?? mfaCode).trim();
    setMfaSubmitting(true);
    if (!(await satisfyMfa(testCode))) {
      setMfaError(t("mfaError"));
      setMfaSubmitting(false);
      return;
    }
    setMfaSubmitting(false);
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
            <Icon name="runner" size={18} strokeWidth={2} />
          </span>
          <span className="brand-name">RunSense</span>
          <span className="brand-phase">RUN / RECOVER</span>
        </div>

        <div className="workspace-switch">
          <div className="segmented" style={{ width: "100%" }}>
            <button
              type="button"
              style={{ flex: 1 }}
              aria-pressed={workspace === "athlete"}
              onClick={() => switchWorkspace("athlete")}
            >
              {t("athlete")}
            </button>
            <button
              type="button"
              style={{ flex: 1 }}
              aria-pressed={workspace === "coach"}
              onClick={() => switchWorkspace("coach")}
            >
              {t("coach")}
            </button>
          </div>
        </div>

        <nav className="nav">
          {nav.map((group) => (
            <div className="nav-section" key={group.section}>
              <div className="nav-section-label">{t(group.section)}</div>
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
                  {t(item.label)}
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
              className="card account-menu"
              role="dialog"
              aria-label={t("account")}
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
                {t(preferences.theme === "dark" ? "themeLight" : "themeDark")}
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
                {t("security")}
              </button>
              <div className="account-menu-language">
                <span className="account-menu-label">
                  <Icon name="translate" size={15} />
                  {t("language")}
                </span>
                <div className="language-options" role="group" aria-label={t("language")}>
                  <button
                    type="button"
                    aria-pressed={locale === "zh-TW"}
                    onClick={() => setLocale("zh-TW")}
                  >
                    中文
                  </button>
                  <button
                    type="button"
                    aria-pressed={locale === "en"}
                    onClick={() => setLocale("en")}
                  >
                    EN
                  </button>
                </div>
              </div>
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
                {t("logout")}
              </button>
            </div>
          )}

          <button
            ref={accountButtonRef}
            className="account-button"
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            onClick={() => setMenuOpen((v) => !v)}
          >
            <Avatar name={auth.athlete.name} />
            <span style={{ minWidth: 0 }}>
              <span className="account-name" style={{ display: "block" }}>
                {workspace === "coach" ? t("coachView") : auth.athlete.name}
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
            <div className="topbar-title">{meta.title === "RunSense" ? meta.title : t(meta.title)}</div>
            {meta.sub && <div className="topbar-sub">{t(meta.sub)}</div>}
          </div>

          <div className="topbar-actions">
            {workspace === "athlete" && (
              <>
                <button
                  className="conn-pill"
                  data-online={online}
                  onClick={() => setOnline(!online)}
                  title={t("connectionHint")}
                >
                  <span className="conn-dot" />
                  {t(online ? "online" : "offline")}
                </button>
                {pendingCount > 0 && (
                  <Button
                    size="sm"
                    variant="secondary"
                    icon="refresh"
                    onClick={() => void syncNow()}
                    disabled={syncing || !online}
                  >
                    {syncing ? t("syncing") : t("syncCount", { count: pendingCount })}
                  </Button>
                )}
              </>
            )}
            <span className="req-tag">{t(apiConfigured ? "live" : "demo")}</span>
          </div>
        </header>

        <main className="content" ref={contentRef}>
          <div className="content-inner">
            <Outlet />
          </div>
        </main>
      </div>

      <nav className="mobile-nav" aria-label={t("primaryNav")}>
        {mobileNav.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              isActive ? "mobile-nav-item is-active" : "mobile-nav-item"
            }
          >
            <span className="mobile-nav-icon">
              <Icon name={item.icon} size={21} />
            </span>
            <span>{t(item.label)}</span>
          </NavLink>
        ))}
        {workspace === "athlete" && (
          <button
            type="button"
            className={mobileMoreActive ? "mobile-nav-item is-active" : "mobile-nav-item"}
            aria-label={t("openMore")}
            aria-expanded={mobileMoreOpen}
            onClick={() => setMobileMoreOpen(true)}
          >
            <span className="mobile-nav-icon">
              <Icon name="settings" size={21} />
            </span>
            <span>{t("more")}</span>
            {invitationCount > 0 && (
              <span className="mobile-nav-badge" aria-label={t("invites", { count: invitationCount })}>
                {invitationCount}
              </span>
            )}
          </button>
        )}
      </nav>

      <Modal
        open={mobileMoreOpen}
        title={t("moreTitle")}
        description={t("moreDescription")}
        onClose={() => setMobileMoreOpen(false)}
      >
        <div className="mobile-more-list">
          {mobileMoreItems.map((item) => (
            <button
              type="button"
              className="mobile-more-item"
              key={item.to}
              onClick={() => {
                setMobileMoreOpen(false);
                navigate(item.to);
              }}
            >
              <span className="mobile-more-icon">
                <Icon name={item.icon} size={20} />
              </span>
              <span>
                <strong>{t(item.label)}</strong>
                <small>{t(MOBILE_MORE_CAPTION[item.to] ?? "moreSettings")}</small>
              </span>
              {item.to === "/app/team" && invitationCount > 0 && (
                <span className="nav-item-count">{invitationCount}</span>
              )}
              <Icon name="chevron-right" size={16} />
            </button>
          ))}
        </div>
        <div className="mobile-language-row">
          <span><Icon name="translate" size={18} /> {t("language")}</span>
          <div className="language-options" role="group" aria-label={t("language")}>
            <button type="button" aria-pressed={locale === "zh-TW"} onClick={() => setLocale("zh-TW")}>中文</button>
            <button type="button" aria-pressed={locale === "en"} onClick={() => setLocale("en")}>EN</button>
          </div>
        </div>
      </Modal>

      <Modal
        open={mfaOpen}
        title={t("mfaTitle")}
        description={t("mfaDescription")}
        onClose={() => setMfaOpen(false)}
        footer={
          <>
            <Button onClick={() => setMfaOpen(false)}>{t("cancel")}</Button>
            <Button
              variant="primary"
              onClick={() => void submitMfa()}
              disabled={mfaCode.length === 0 || mfaSubmitting}
            >
              {mfaSubmitting ? t("verifying") : t("verifySwitch")}
            </Button>
          </>
        }
      >
        <div className="stack">
          <Field
            label={t("mfaLabel")}
            htmlFor="mfa-code"
            error={mfaError}
            hint={t("mfaHint", { code: DEMO_MFA_CODE })}
          >
            <OtpInput
              id="mfa-code"
              value={mfaCode}
              onChange={(val) => {
                setMfaCode(val);
                setMfaError(null);
              }}
              onComplete={(fullCode) => {
                void submitMfa(fullCode);
              }}
              error={Boolean(mfaError)}
            />
          </Field>
          <Notice tone="neutral" icon="lock">
            {t("mfaNotice")}
          </Notice>
        </div>
      </Modal>
    </div>
  );
}
