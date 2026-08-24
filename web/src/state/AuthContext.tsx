/* oxlint-disable react/only-export-components -- provider hooks and demo constants share context */
/* Authentication + the actor/target distinction the SRS insists on.
 *
 * REQ-RLS-006: `actor` is who is operating. A target athlete id read off a URL
 * is never promoted into the auth context — the coach screens take an athlete
 * id as a *parameter* and check it against the roster the actor is allowed to
 * see, which is why `canViewAthlete` lives here rather than in the screen.
 *
 * REQ-AUTH-006: the access token is held in memory only. It is never written
 * to localStorage, so a reload requires logging in again — deliberate.
 * REQ-AUTH-007: switching into a head_coach view requires MFA in this session.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import { DEMO_ATHLETE, DEMO_COACH } from "../data/demoData.ts";
import { apiConfigured, demoLogin, verifyMyMfa, ApiError } from "../data/apiClient.ts";
import type { Actor, Athlete } from "../lib/types.ts";
import { useLocale } from "./LocaleContext.tsx";

export type Workspace = "athlete" | "coach";
export type AuthMode = "demo" | "api";

interface AuthState {
  actor: Actor;
  athlete: Athlete;
  accessToken: string | null;
  mode: AuthMode;
  signedInAtUtc: string;
}

interface AuthContextValue {
  auth: AuthState | null;
  workspace: Workspace;
  loginPending: boolean;
  loginError: string | null;
  login: (email: string, password: string) => Promise<boolean>;
  logout: () => void;
  /** Returns false when MFA is still outstanding (REQ-AUTH-007). */
  enterWorkspace: (workspace: Workspace) => boolean;
  satisfyMfa: (code: string) => Promise<boolean>;
  canViewAthlete: (athleteId: string, rosterIds: string[]) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export interface DemoCredential {
  email: string;
  password: string;
  label: string;
  name: string;
  role: "coach" | "athlete";
  timezone: string;
  city: string;
}

/** Demo credentials, matching backend/scripts/seed_demo_personas.py. */
export const DEMO_CREDENTIALS: DemoCredential[] = [
  {
    email: "runner.taipei@runsense.demo",
    password: "TaipeiDemo!2026",
    label: "臺北教練（Asia/Taipei）",
    name: "王士豪",
    role: "coach",
    timezone: "Asia/Taipei",
    city: "臺北市",
  },
  {
    email: "runner.tokyo@runsense.demo",
    password: "TokyoDemo!2026",
    label: "東京選手（Asia/Tokyo）",
    name: "佐藤 健",
    role: "athlete",
    timezone: "Asia/Tokyo",
    city: "Tokyo",
  },
  {
    email: "runner.london@runsense.demo",
    password: "LondonDemo!2026",
    label: "倫敦選手（Europe/London）",
    name: "Oliver Smith",
    role: "athlete",
    timezone: "Europe/London",
    city: "London",
  },
];

/** The one code the demo MFA challenge accepts. */
export const DEMO_MFA_CODE = "424242";

export function AuthProvider({ children }: { children: ReactNode }) {
  const { t } = useLocale();
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [workspace, setWorkspace] = useState<Workspace>("athlete");
  const [loginPending, setLoginPending] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);

  const login = useCallback(async (email: string, password: string) => {
    setLoginPending(true);
    setLoginError(null);

    const known = DEMO_CREDENTIALS.find((c) => c.email === email.trim());

    try {
      // With a backend configured, the real endpoint decides. Without one, the
      // seeded credential list does — and the UI says which happened.
      if (apiConfigured) {
        const result = await demoLogin(email.trim(), password);
        setAuth({
          actor: {
            userId: DEMO_ATHLETE.id,
            name: DEMO_ATHLETE.name,
            email: email.trim(),
            role: "athlete",
            mfaSatisfied: false,
          },
          athlete: { ...DEMO_ATHLETE, email: email.trim() },
          accessToken: result.accessToken,
          mode: "api",
          signedInAtUtc: new Date().toISOString(),
        });
        setWorkspace("athlete");
        return true;
      }

      if (!known || known.password !== password) {
        setLoginError(t("loginInvalid"));
        return false;
      }

      setAuth({
        actor: {
          userId: DEMO_ATHLETE.id,
          name: known.name,
          email: known.email,
          role: "athlete",
          mfaSatisfied: false,
        },
        athlete: {
          ...DEMO_ATHLETE,
          name: known.name,
          email: known.email,
          timezone: known.timezone,
          city: known.city,
        },
        accessToken: null,
        mode: "demo",
        signedInAtUtc: new Date().toISOString(),
      });
      setWorkspace("athlete");
      return true;
    } catch (err) {
      setLoginError(err instanceof ApiError && err.status === 401 ? t("loginInvalid") : t("serverOffline"));
      return false;
    } finally {
      setLoginPending(false);
    }
  }, [t]);

  const logout = useCallback(() => {
    // REQ-LOCAL-SEC-003: logging out clears this account's cached state. The
    // token was in memory only, so dropping the state is the whole cleanup.
    setAuth(null);
    setWorkspace("athlete");
    setLoginError(null);
  }, []);

  const enterWorkspace = useCallback(
    (next: Workspace) => {
      if (next === "athlete") {
        setWorkspace("athlete");
        return true;
      }
      // Coach workspace implies head_coach here, so MFA must already be met.
      if (!auth?.actor.mfaSatisfied) return false;
      setWorkspace("coach");
      return true;
    },
    [auth],
  );

  const satisfyMfa = useCallback(
    async (code: string) => {
      if (code.trim() !== DEMO_MFA_CODE) return false;
      if (apiConfigured && auth?.accessToken) {
        try {
          await verifyMyMfa(auth.accessToken, code.trim());
        } catch {
          return false;
        }
      }
      setAuth((current) =>
        current
          ? {
              ...current,
              actor: {
                ...current.actor,
                role: "head_coach",
                mfaSatisfied: true,
              },
            }
          : current,
      );
      setWorkspace("coach");
      return true;
    },
    [auth],
  );

  /** REQ-RLS-006 in the UI layer: an athlete id from the URL only resolves if
   *  it is in the roster the *actor* is authorized for. The id itself grants
   *  nothing. */
  const canViewAthlete = useCallback(
    (athleteId: string, rosterIds: string[]) => {
      if (!auth) return false;
      if (athleteId === auth.athlete.id) return true;
      if (auth.actor.role === "athlete") return false;
      return rosterIds.includes(athleteId);
    },
    [auth],
  );

  const value = useMemo(
    () => ({
      auth,
      workspace,
      loginPending,
      loginError,
      login,
      logout,
      enterWorkspace,
      satisfyMfa,
      canViewAthlete,
    }),
    [
      auth,
      workspace,
      loginPending,
      loginError,
      login,
      logout,
      enterWorkspace,
      satisfyMfa,
      canViewAthlete,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export const COACH_IDENTITY = DEMO_COACH;
