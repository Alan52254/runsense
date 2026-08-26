import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "../components/Icon.tsx";
import { Button, Field, Notice } from "../components/ui.tsx";
import { DEMO_CREDENTIALS, useAuth } from "../state/AuthContext.tsx";
import { apiConfigured } from "../data/apiClient.ts";
import { useLocale } from "../state/LocaleContext.tsx";

export function LoginScreen() {
  const navigate = useNavigate();
  const { login, loginPending, loginError } = useAuth();
  const { locale, setLocale, t } = useLocale();
  const points = [t("loginPointOffline"), t("loginPointLoad"), t("loginPointConsent")];

  const [email, setEmail] = useState(DEMO_CREDENTIALS[0].email);
  const [password, setPassword] = useState(DEMO_CREDENTIALS[0].password);
  const [ageDeclared, setAgeDeclared] = useState(true);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const ok = await login(email, password);
    if (ok) navigate("/app");
  }

  return (
    <div className="auth-page">
      <aside className="auth-aside">
        <div className="auth-aside-brand">
          <span className="brand-mark">
            <Icon name="runner" size={18} strokeWidth={2} />
          </span>
          RunSense
        </div>

        <div>
          <h1 className="auth-headline">{t("loginHeadline")}</h1>
          <p className="auth-sub">
            {t("loginIntro")}
          </p>
          <ul className="auth-points">
            {points.map((point) => (
              <li className="auth-point" key={point}>
                <span className="auth-point-mark">
                  <Icon name="check" size={15} strokeWidth={2.2} />
                </span>
                {point}
              </li>
            ))}
          </ul>
        </div>

        <p className="auth-foot">{t("loginTagline")}</p>
      </aside>

      <section className="auth-panel">
        <form className="auth-form" onSubmit={submit}>
          <div className="login-language" role="group" aria-label={t("language")}>
            <button type="button" aria-pressed={locale === "zh-TW"} onClick={() => setLocale("zh-TW")}>
              中文
            </button>
            <button type="button" aria-pressed={locale === "en"} onClick={() => setLocale("en")}>
              EN
            </button>
          </div>
          <div>
            <h1 className="auth-title">{t("loginTitle")}</h1>
            <p className="auth-desc">
              {apiConfigured
                ? t("loginConnected")
                : t("loginDemo")}
            </p>
          </div>

          <Field label={t("email")} htmlFor="login-email">
            <input
              id="login-email"
              className="input"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </Field>

          <Field
            label={t("password")}
            htmlFor="login-password"
            hint={t("passwordHint")}
          >
            <input
              id="login-password"
              className="input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </Field>

          <label className="row" style={{ alignItems: "flex-start", gap: 10 }}>
            <input
              type="checkbox"
              checked={ageDeclared}
              onChange={(e) => setAgeDeclared(e.target.checked)}
              style={{ marginTop: 3 }}
            />
            <span className="field-hint" style={{ color: "var(--text-2)" }}>
              {t("age")}
            </span>
          </label>

          {loginError && (
            <Notice tone="critical" icon="alert">
              {loginError}
            </Notice>
          )}

          <Button
            type="submit"
            variant="primary"
            size="lg"
            block
            disabled={loginPending || !ageDeclared}
          >
            {loginPending ? t("signingIn") : t("signIn")}
          </Button>

          <div className="stack-sm">
            <span className="field-hint" style={{ fontWeight: 600 }}>{t("personas")}</span>

            {/* Coach Section */}
            <div className="persona-group">
              <div className="persona-group-title">
                <Icon name="assignment" size={13} />
                <span>{t("coachAccounts")}</span>
              </div>
              {DEMO_CREDENTIALS.filter((p) => p.role === "coach").map((persona) => (
                <button
                  type="button"
                  key={persona.email}
                  className="persona-button"
                  onClick={() => {
                    setEmail(persona.email);
                    setPassword(persona.password);
                  }}
                >
                  <div className="row" style={{ gap: 10 }}>
                    <div className="persona-avatar persona-avatar-coach">
                      {persona.name.slice(0, 2)}
                    </div>
                    <div>
                      <div className="row" style={{ gap: 6, alignItems: "center" }}>
                        <strong>{persona.name}</strong>
                        <span className="persona-badge persona-badge-coach">{t("coach")}</span>
                      </div>
                      <span className="persona-mail" style={{ fontSize: 11.5 }}>
                        {persona.email} · {persona.timezone}
                      </span>
                    </div>
                  </div>
                  <Icon name="chevron-right" size={15} />
                </button>
              ))}
            </div>

            {/* Athletes Section */}
            <div className="persona-group">
              <div className="persona-group-title">
                <Icon name="runner" size={13} />
                <span>{t("athleteAccounts")}</span>
              </div>
              {DEMO_CREDENTIALS.filter((p) => p.role === "athlete").map((persona) => (
                <button
                  type="button"
                  key={persona.email}
                  className="persona-button"
                  onClick={() => {
                    setEmail(persona.email);
                    setPassword(persona.password);
                  }}
                >
                  <div className="row" style={{ gap: 10 }}>
                    <div className="persona-avatar">
                      {persona.name.slice(0, 2)}
                    </div>
                    <div>
                      <div className="row" style={{ gap: 6, alignItems: "center" }}>
                        <strong>{persona.name}</strong>
                        <span className="persona-badge persona-badge-athlete">{persona.city}</span>
                      </div>
                      <span className="persona-mail" style={{ fontSize: 11.5 }}>
                        {persona.email} · {persona.timezone}
                      </span>
                    </div>
                  </div>
                  <Icon name="chevron-right" size={15} />
                </button>
              ))}
            </div>
          </div>

          <p className="field-hint">{t("refreshLogin")}</p>
        </form>
      </section>
    </div>
  );
}
