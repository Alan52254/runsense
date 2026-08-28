import { NavLink, Outlet } from "react-router-dom";
import { useLocale } from "../../../state/LocaleContext.tsx";

export function SettingsLayout() {
  const { locale } = useLocale();
  const en = locale === "en";
  const tabs = [
    { to: "/app/settings/profile", label: en ? "Profile" : "個人資料" },
    { to: "/app/settings/security", label: en ? "Security" : "安全" },
    { to: "/app/settings/privacy", label: en ? "Privacy & data" : "隱私與資料" },
    { to: "/app/settings/integrations", label: en ? "Integrations & notifications" : "整合與通知" },
  ];

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{en ? "Settings" : "設定"}</h1>
          <p className="page-desc">
            {en
              ? "Manage your profile, sign-in security, privacy rights, and external integrations."
              : "個人資料、登入安全、隱私權利與外部整合。"}
          </p>
        </div>
      </div>

      <nav className="subnav">
        {tabs.map((tab) => (
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
