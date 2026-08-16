import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "../components/Icon.tsx";
import { Button, Field, Notice } from "../components/ui.tsx";
import { DEMO_CREDENTIALS, useAuth } from "../state/AuthContext.tsx";
import { apiConfigured, API_BASE_URL } from "../data/apiClient.ts";

const POINTS = [
  "手動輸入的訓練摘要，離線也能存；顯示「已儲存」之前一定先寫入本地資料庫。",
  "訓練負荷只呈現趨勢數字與資料品質，不做紅黃綠燈號。",
  "身體狀況的「有無不適」與「自述原文」是兩個獨立授權，不是一個開關。",
];

export function LoginScreen() {
  const navigate = useNavigate();
  const { login, loginPending, loginError } = useAuth();

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
          <h1 className="auth-headline">把訓練資料的主導權留在選手身上</h1>
          <p className="auth-sub">
            RunSense 的每一份完成訓練、訓練負荷與身體自述，都是選手本人擁有的正典紀錄。教練看得到什麼，由選手逐項授權決定。
          </p>
          <ul className="auth-points">
            {POINTS.map((point) => (
              <li className="auth-point" key={point}>
                <span className="auth-point-mark">
                  <Icon name="check" size={15} strokeWidth={2.2} />
                </span>
                {point}
              </li>
            ))}
          </ul>
        </div>

        <p className="auth-foot">
          Phase 1A · 手動輸入。Garmin 同步為 feature-gated（Phase 1B），行動端即時 GPS 錄跑屬 Phase 2。
        </p>
      </aside>

      <section className="auth-panel">
        <form className="auth-form" onSubmit={submit}>
          <div>
            <h1 className="auth-title">登入 RunSense</h1>
            <p className="auth-desc">
              {apiConfigured
                ? `將透過 ${API_BASE_URL}/auth/demo-login 驗證。`
                : "目前未設定後端位址，登入會使用內建示範資料。"}
            </p>
          </div>

          <Field label="電子郵件" htmlFor="login-email">
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
            label="密碼"
            htmlFor="login-password"
            hint="示範帳號的密碼已預先填入。"
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
              我聲明已年滿 18 歲。系統只保存這個勾選與時間戳，不會保存完整出生年月日。
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
            {loginPending ? "驗證中…" : "登入"}
          </Button>

          <div className="stack-sm">
            <span className="field-hint">示範帳號（點一下即可填入）</span>
            <div className="persona-list">
              {DEMO_CREDENTIALS.map((persona) => (
                <button
                  type="button"
                  key={persona.email}
                  className="persona-button"
                  onClick={() => {
                    setEmail(persona.email);
                    setPassword(persona.password);
                  }}
                >
                  <span>
                    <strong style={{ display: "block" }}>{persona.label}</strong>
                    <span className="persona-mail">{persona.email}</span>
                  </span>
                  <Icon name="chevron-right" size={15} />
                </button>
              ))}
            </div>
          </div>

          <p className="field-hint">
            登入後的存取權杖只保存在記憶體中，不寫入 localStorage；重新整理頁面需要重新登入。
          </p>
        </form>
      </section>
    </div>
  );
}
