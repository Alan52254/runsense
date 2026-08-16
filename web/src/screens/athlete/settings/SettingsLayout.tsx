import { NavLink, Outlet } from "react-router-dom";

const TABS = [
  { to: "/app/settings/profile", label: "個人資料" },
  { to: "/app/settings/security", label: "安全" },
  { to: "/app/settings/privacy", label: "隱私與資料" },
  { to: "/app/settings/integrations", label: "整合與通知" },
];

export function SettingsLayout() {
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">設定</h1>
          <p className="page-desc">
            個人資料、登入安全、隱私權利與外部整合。這裡的每一項都對應規格書中的一條需求。
          </p>
        </div>
      </div>

      <nav className="subnav">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={({ isActive }) => (isActive ? "is-active" : "")}
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>

      <Outlet />
    </>
  );
}
