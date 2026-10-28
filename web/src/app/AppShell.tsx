import { Surface } from "../components/Surface.tsx";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { BrandMark } from "../components/BrandMark.tsx";
import { Icon } from "../components/Icon.tsx";
import type { IconName } from "../components/Icon.tsx";
import { Button, Modal, Field, Notice } from "../components/ui.tsx";
import { OtpInput } from "../components/OtpInput.tsx";
import { CoachChatDrawer } from "../components/CoachChatDrawer.tsx";
import { Ticker } from "../components/motion.tsx";
import type { TickerItem } from "../components/motion.tsx";
import { ShellTickerContext } from "./shellTicker.tsx";
import type { ShellTickerContribution } from "./shellTicker.tsx";
import { useCoachChat } from "../state/CoachChatContext.tsx";
import { TeamChatPanel } from "../components/TeamChatPanel.tsx";
import { apiConfigured as chatApiConfigured, getChatRooms } from "../data/apiClient.ts";
import { useAuth, DEMO_MFA_CODE } from "../state/AuthContext.tsx";
import type { Workspace } from "../state/AuthContext.tsx";
import { useWorkspace } from "../state/WorkspaceContext.tsx";
import { useLocale } from "../state/LocaleContext.tsx";
import type { MessageKey } from "../state/LocaleContext.tsx";

interface NavEntry {
  to: string;
  /** a locale key, or literal text for entries without one */
  label: MessageKey | { zh: string; en: string };
  icon: IconName;
  end?: boolean;
}

const HEALTH_COACH = { zh: "健康教練", en: "Health Coach" };

const ATHLETE_NAV: { section: MessageKey; items: NavEntry[] }[] = [
  {
    section: "training",
    items: [
      { to: "/app", label: "dashboard", icon: "home", end: true },
      { to: "/app/plan", label: "coachPlan", icon: "assignment" },
      { to: "/app/run", label: "liveRun", icon: "runner" },
      { to: "/app/log", label: "log", icon: "shoe" },
      { to: "/app/history", label: "history", icon: "history" },
      { to: "/app/load", label: "load", icon: "trend" },
      { to: "/app/body", label: "body", icon: "body-status" },
      { to: "/app/coach-chat", label: HEALTH_COACH, icon: "coach-note" },
      { to: "/app/method", label: "method", icon: "activity" },
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
      { to: "/coach/review", label: "scheduleReview", icon: "calendar" },
      { to: "/coach/assignments", label: "assignments", icon: "assignment" },
      { to: "/coach/coach-chat", label: HEALTH_COACH, icon: "coach-note" },
    ],
  },
];

const PAGE_META: Record<string, { title: MessageKey; sub: MessageKey }> = {
  "/app": { title: "dashboard", sub: "dashboardMeta" },
  "/app/run": { title: "liveRun", sub: "liveRunMeta" },
  "/app/log": { title: "log", sub: "logMeta" },
  "/app/history": { title: "history", sub: "historyMeta" },
  "/app/plan": { title: "coachPlan", sub: "coachPlanMeta" },
  "/app/load": { title: "load", sub: "loadMeta" },
  "/app/body": { title: "body", sub: "bodyMeta" },
  "/app/method": { title: "method", sub: "methodMeta" },
  "/app/team": { title: "team", sub: "teamMeta" },
  "/app/settings": { title: "settings", sub: "settingsMeta" },
  "/coach": { title: "teamOverview", sub: "teamOverviewMeta" },
  "/coach/review": { title: "scheduleReview", sub: "scheduleReviewMeta" },
  "/coach/assignments": { title: "assignments", sub: "assignmentsMeta" },
};

// phone bottom bar (athlete): the rest goes under "more"
const ATHLETE_MOBILE_TABS = ["/app", "/app/plan", "/app/run", "/app/history"];

const MOBILE_MORE_CAPTION: Record<string, MessageKey> = {
  "/app/log": "moreLog",
  "/app/load": "moreLoad",
  "/app/body": "moreBody",
  "/app/method": "moreMethod",
  "/app/team": "moreTeam",
  "/app/settings": "moreSettings",
};

const isCoachChatPath = (pathname: string) => /^\/(app|coach)\/coach-chat\/?$/.test(pathname);

function pageMetaFor(pathname: string): { title: MessageKey | "RunSense"; sub: MessageKey | "" } {
  if (pathname.startsWith("/app/settings")) return PAGE_META["/app/settings"];
  if (pathname.startsWith("/coach/athletes"))
    return { title: "athleteDetail", sub: "athleteDetailMeta" };
  return PAGE_META[pathname] ?? { title: "RunSense", sub: "" };
}

/** 選手 / 教練: the sidebar's switch, and the same control inside the phone's
 *  更多 sheet, where the sidebar is hidden. The MFA step is the caller's. */
function WorkspaceSwitch({ workspace, onSwitch }: { workspace: Workspace; onSwitch: (next: Workspace) => void }) {
  const { t } = useLocale();
  return (
    <div className="segmented workspace-segments" role="group" aria-label={t("workspaceLabel")}>
      <button type="button" aria-pressed={workspace === "athlete"} onClick={() => onSwitch("athlete")}>
        {t("athlete")}
      </button>
      <button type="button" aria-pressed={workspace === "coach"} onClick={() => onSwitch("coach")}>
        {t("coach")}
      </button>
    </div>
  );
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
    refreshAssignments,
  } = useWorkspace();

  const [menuOpen, setMenuOpen] = useState(false);
  const [screenTicker, setScreenTicker] = useState<ShellTickerContribution | null>(null);
  // the shell's own ambient status; a screen appends weather, load, triage
  const tickerItems = useMemo<TickerItem[]>(() => {
    const en = locale === "en";
    // the athlete header already carries the connection toggle at its right
    // edge; saying 連線良好 twice is noise, so the ticker only carries it
    // where that toggle is absent (coach workspace)
    const connection: TickerItem[] = workspace === "athlete" ? [] : [
      {
        id: "connection",
        icon: online ? "wifi" : "wifi-off",
        tone: online ? "safe" : "alert",
        text: t(online ? "online" : "offline"),
      },
    ];
    const shell: TickerItem[] = [
      ...connection,
      {
        id: "sync",
        icon: "refresh",
        tone: pendingCount > 0 ? "brand" : "neutral",
        text: syncing
          ? t("syncing")
          : pendingCount > 0
            ? t("syncCount", { count: pendingCount })
            : en ? "All records synced" : "紀錄已全部同步",
      },
    ];
    return [...(screenTicker?.items ?? []), ...shell];
  }, [locale, online, pendingCount, syncing, screenTicker, t, workspace]);
  const [mobileMoreOpen, setMobileMoreOpen] = useState(false);
  const { openCoach, closeCoach } = useCoachChat();
  const onCoachPage = isCoachChatPath(location.pathname);
  // the page is the conversation; a drawer over it would be a second copy
  useEffect(() => {
    if (onCoachPage) closeCoach();
  }, [onCoachPage, closeCoach]);
  const [teamChatOpen, setTeamChatOpen] = useState(false);
  // 團隊課表審核 opens the chat on one athlete's room
  const [chatFocusRoom, setChatFocusRoom] = useState<{ roomId: string; at: number } | null>(null);
  useEffect(() => {
    const onOpen = (e: Event) => {
      const roomId = (e as CustomEvent<{ roomId: string }>).detail?.roomId;
      if (!roomId) return;
      setChatFocusRoom({ roomId, at: Date.now() });
      setTeamChatOpen(true);
    };
    window.addEventListener("runsense:open-chat", onOpen);
    return () => window.removeEventListener("runsense:open-chat", onOpen);
  }, []);
  const [chatUnread, setChatUnread] = useState(0);
  const chatToken = auth?.accessToken ?? null;
  // the latest refreshAssignments without restarting the poll when it changes
  const refreshAssignmentsRef = useRef(refreshAssignments);
  refreshAssignmentsRef.current = refreshAssignments;
  // unread badge: poll the room list every 3 s (the panel polls its own room).
  // Any new message in any room (e.g. the "已排入…" notice after a coach
  // confirms a plan, or a revoke) also re-fetches assignments, so today's
  // workout and the coach's schedule update without logging in again.
  useEffect(() => {
    if (!chatApiConfigured || !chatToken) return;
    let alive = true;
    let lastSeen: string | null = null;
    const tick = async () => {
      try {
        const r = await getChatRooms(chatToken);
        if (!alive) return;
        setChatUnread(r.unread_total);
        const seen = r.rooms.map((room) => `${room.id}:${room.last_at ?? ""}`).join("|");
        if (lastSeen !== null && seen !== lastSeen) void refreshAssignmentsRef.current();
        lastSeen = seen;
      } catch {
        /* offline: keep the last count */
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 3000);
    return () => { alive = false; window.clearInterval(id); };
  }, [chatToken]);
  const [mfaOpen, setMfaOpen] = useState(false);
  const [mfaCode, setMfaCode] = useState("");
  const [mfaError, setMfaError] = useState<string | null>(null);
  const [mfaSubmitting, setMfaSubmitting] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const accountButtonRef = useRef<HTMLButtonElement | null>(null);
  const contentRef = useRef<HTMLElement | null>(null);
  const topbarTitleRef = useRef<HTMLDivElement | null>(null);

  // .content (not window) is the actual scroll container -- a route change
  // otherwise leaves it wherever the previous page's scroll happened to be.
  // useLayoutEffect (not useEffect) so this runs before the browser paints
  // the new route's content -- otherwise the old scroll position flashes
  // on screen for one frame before snapping back to the top.
  useLayoutEffect(() => {
    contentRef.current?.scrollTo(0, 0);
  }, [location.pathname]);

  // The top bar names the page. A screen heading that only repeats that
  // name is kept for assistive tech but not printed a second time.
  useLayoutEffect(() => {
    const root = contentRef.current;
    if (!root) return;
    const mark = () => {
      const title = topbarTitleRef.current?.textContent?.trim();
      root.querySelectorAll<HTMLElement>(".page-title").forEach((el) => {
        const dup = Boolean(title) && el.textContent?.trim() === title;
        if (el.classList.contains("is-shell-title") !== dup) el.classList.toggle("is-shell-title", dup);
      });
    };
    mark();
    const observer = new MutationObserver(mark);
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [location.pathname, locale]);

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
  const athleteItems = ATHLETE_NAV.flatMap((group) => group.items);
  const mobileNav =
    workspace === "athlete"
      ? ATHLETE_MOBILE_TABS.map((to) => athleteItems.find((item) => item.to === to)!).filter(Boolean)
      : (nav[0]?.items ?? []);
  const mobileMoreItems =
    workspace === "athlete" ? athleteItems.filter((item) => !ATHLETE_MOBILE_TABS.includes(item.to)) : [];
  const mobileMoreActive = mobileMoreItems.some((item) =>
    location.pathname.startsWith(item.to),
  );
  const meta = pageMetaFor(location.pathname);
  const navLabel = (label: NavEntry["label"]) =>
    typeof label === "string" ? t(label) : locale === "en" ? label.en : label.zh;
  const pageTitle = onCoachPage
    ? navLabel(HEALTH_COACH)
    : meta.title === "RunSense"
      ? meta.title
      : t(meta.title);
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
    <ShellTickerContext.Provider value={setScreenTicker}>
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <BrandMark variant="mark" size="md" />
          <span className="brand-name">RunSense</span>
        </div>

        <div className="workspace-switch">
          <WorkspaceSwitch workspace={workspace} onSwitch={switchWorkspace} />
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
                  {navLabel(item.label)}
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
            <Surface padding="sm"
              className="account-menu"
              role="dialog"
              aria-label={t("account")}
              style={{
                position: "absolute",
                bottom: "calc(100% - 4px)",
                left: 12,
                right: 12,
                boxShadow: "var(--shadow-lg)",
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
            </Surface>
          )}

          <button
            ref={accountButtonRef}
            className="account-button"
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            onClick={() => setMenuOpen((v) => !v)}
          >
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
          <div className="topbar-title" ref={topbarTitleRef}>
            {pageTitle}
          </div>

          <div className="topbar-ticker">
            <Ticker
              items={tickerItems}
              label={locale === "en" ? "Live status" : "即時狀態"}
              onOpenDetails={screenTicker?.onOpenDetails}
              detailsLabel={screenTicker?.detailsLabel ?? (locale === "en" ? "Details" : "詳細資訊")}
            />
          </div>

          <div className="topbar-actions">
            {workspace === "athlete" && pendingCount > 0 && (
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
            {chatApiConfigured && chatToken && (
              <button
                type="button"
                className="btn btn-sm btn-secondary team-chat-trigger"
                onClick={() => setTeamChatOpen(true)}
                aria-haspopup="dialog"
              >
                <Icon name="coach-note" size={15} />
                <span>{locale === "en" ? "Team Chat" : "聊天室"}</span>
                {chatUnread > 0 && <span className="chat-unread">{chatUnread > 99 ? "99+" : chatUnread}</span>}
              </button>
            )}
            <button
              type="button"
              className="btn btn-sm btn-secondary health-coach-trigger"
              // on the 健康教練 page the button says where you are instead of
              // opening a second copy of the conversation
              onClick={onCoachPage ? undefined : () => openCoach()}
              aria-haspopup={onCoachPage ? undefined : "dialog"}
              aria-label={locale === "en" ? "Health Coach" : "健康教練"}
            >
              <Icon name="heart" size={15} />
              <span className="label-full">{locale === "en" ? "Health Coach" : "健康教練"}</span>
              <span className="label-short">{locale === "en" ? "Health Coach" : "健康教練"}</span>
            </button>
            {workspace === "athlete" && (
              <button
                type="button"
                className="conn-toggle"
                aria-pressed={online}
                aria-label={t(online ? "online" : "offline")}
                onClick={() => setOnline(!online)}
                title={t("connectionHint")}
              >
                <span className="conn-dot" aria-hidden="true" />
                <span className="conn-label">{t(online ? "online" : "offline")}</span>
              </button>
            )}
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
            <span>{navLabel(item.label)}</span>
          </NavLink>
        ))}
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
          {workspace === "athlete" && invitationCount > 0 && (
            <span className="mobile-nav-badge" aria-label={t("invites", { count: invitationCount })}>
              {invitationCount}
            </span>
          )}
        </button>
      </nav>

      <Modal
        open={mobileMoreOpen}
        title={t("moreTitle")}
        description={t(workspace === "coach" ? "moreDescriptionCoach" : "moreDescription")}
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
                <strong>{navLabel(item.label)}</strong>
                <small>
                  {isCoachChatPath(item.to)
                    ? locale === "en"
                      ? "Ask about today's run, pace or how you feel"
                      : "問今天的課表、配速或哪裡不舒服"
                    : t(MOBILE_MORE_CAPTION[item.to] ?? "moreSettings")}
                </small>
              </span>
              {item.to === "/app/team" && invitationCount > 0 && (
                <span className="nav-item-count">{invitationCount}</span>
              )}
              <Icon name="chevron-right" size={16} />
            </button>
          ))}
        </div>
        <div className="mobile-language-row mobile-workspace-row">
          <span><Icon name="users" size={18} /> {t("workspaceLabel")}</span>
          <WorkspaceSwitch
            workspace={workspace}
            onSwitch={(next) => {
              setMobileMoreOpen(false);
              switchWorkspace(next);
            }}
          />
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

      <CoachChatDrawer />
      {chatToken && (
        <TeamChatPanel open={teamChatOpen} onClose={() => setTeamChatOpen(false)} accessToken={chatToken} focusRoom={chatFocusRoom} onAssignmentsChanged={() => void refreshAssignments()} />
      )}
    </div>
    </ShellTickerContext.Provider>
  );
}
