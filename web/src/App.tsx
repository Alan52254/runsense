import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./state/AuthContext.tsx";
import { ToastProvider } from "./state/ToastContext.tsx";
import { WorkspaceProvider } from "./state/WorkspaceContext.tsx";
import { LiveRunProvider } from "./state/LiveRunContext.tsx";
import { LocaleProvider } from "./state/LocaleContext.tsx";
import { ToastHost } from "./components/ToastHost.tsx";
import { AppShell } from "./app/AppShell.tsx";
import { LoginScreen } from "./screens/LoginScreen.tsx";
import { DashboardScreen } from "./screens/athlete/DashboardScreen.tsx";
import { LogWorkoutScreen } from "./screens/athlete/LogWorkoutScreen.tsx";
import { LiveRunScreen } from "./screens/athlete/LiveRunScreen.tsx";
import { HistoryScreen } from "./screens/athlete/HistoryScreen.tsx";
import { GarminCsvImportScreen } from "./screens/athlete/GarminCsvImportScreen.tsx";
import { TrainingLoadScreen } from "./screens/athlete/TrainingLoadScreen.tsx";
import { BodyStatusScreen } from "./screens/athlete/BodyStatusScreen.tsx";
import { TeamScreen } from "./screens/athlete/TeamScreen.tsx";
import { SettingsLayout } from "./screens/athlete/settings/SettingsLayout.tsx";
import { ProfileSettings } from "./screens/athlete/settings/ProfileSettings.tsx";
import { SecuritySettings } from "./screens/athlete/settings/SecuritySettings.tsx";
import { PrivacySettings } from "./screens/athlete/settings/PrivacySettings.tsx";
import { IntegrationSettings } from "./screens/athlete/settings/IntegrationSettings.tsx";
import { TeamOverviewScreen } from "./screens/coach/TeamOverviewScreen.tsx";
import { AthleteDetailScreen } from "./screens/coach/AthleteDetailScreen.tsx";
import { AssignmentsScreen } from "./screens/coach/AssignmentsScreen.tsx";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";
import "./styles/layout.css";
import "./styles/charts.css";

/** Signed-out visitors always land on /login; the token lives in memory only,
 *  so a refresh legitimately sends them back there (REQ-AUTH-006). */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const { auth } = useAuth();
  if (!auth) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/** REQ-AUTH-007: the coach workspace implies a head_coach role, which cannot
 *  be entered until MFA has been satisfied in this session. */
function RequireCoach({ children }: { children: React.ReactNode }) {
  const { auth } = useAuth();
  if (!auth) return <Navigate to="/login" replace />;
  if (!auth.actor.mfaSatisfied) return <Navigate to="/app" replace />;
  return <>{children}</>;
}

function AppRoutes() {
  const { auth } = useAuth();

  return (
    <Routes>
      <Route
        path="/login"
        element={auth ? <Navigate to="/app" replace /> : <LoginScreen />}
      />

      <Route
        path="/app"
        element={
          <RequireAuth>
            <AppShell workspace="athlete" />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardScreen />} />
        <Route path="run" element={<LiveRunScreen />} />
        <Route path="log" element={<LogWorkoutScreen />} />
        <Route path="history" element={<HistoryScreen />} />
        <Route path="import" element={<GarminCsvImportScreen />} />
        <Route path="load" element={<TrainingLoadScreen />} />
        <Route path="body" element={<BodyStatusScreen />} />
        <Route path="team" element={<TeamScreen />} />
        <Route path="settings" element={<SettingsLayout />}>
          <Route index element={<Navigate to="profile" replace />} />
          <Route path="profile" element={<ProfileSettings />} />
          <Route path="security" element={<SecuritySettings />} />
          <Route path="privacy" element={<PrivacySettings />} />
          <Route path="integrations" element={<IntegrationSettings />} />
        </Route>
      </Route>

      <Route
        path="/coach"
        element={
          <RequireCoach>
            <AppShell workspace="coach" />
          </RequireCoach>
        }
      >
        <Route index element={<TeamOverviewScreen />} />
        <Route path="athletes/:athleteId" element={<AthleteDetailScreen />} />
        <Route path="assignments" element={<AssignmentsScreen />} />
      </Route>

      <Route path="*" element={<Navigate to={auth ? "/app" : "/login"} replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <LocaleProvider>
        <ToastProvider>
          <AuthProvider>
            <WorkspaceProvider>
              <LiveRunProvider>
                <AppRoutes />
                <ToastHost />
              </LiveRunProvider>
            </WorkspaceProvider>
          </AuthProvider>
        </ToastProvider>
      </LocaleProvider>
    </BrowserRouter>
  );
}
