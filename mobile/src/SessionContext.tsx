import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { clearToken, getToken, saveToken } from './session';
import { ApiError } from './api';

// The deep module for this app's session concept -- see design.md
// Decision 5 and the codebase-design pass that shaped this interface.
// Screens never touch expo-secure-store, never check response status
// codes for "was this an auth failure", and never race the async
// restore-on-launch step against navigation's first render. All three
// live here, once, behind three things a caller needs to know:
// `status`, `login`, and `request`.

export type SessionStatus = 'restoring' | 'authenticated' | 'unauthenticated';

interface SessionContextValue {
  status: SessionStatus;
  login: (token: string) => Promise<void>;
  logout: () => Promise<void>;
  // Centralizes the "any authenticated request rejected for an auth
  // reason ends the session" rule (spec.md "Expired or Rejected Token
  // Falls Back to Login") so individual screens can't forget it. Screens
  // supply a function that needs the current token; this resolves it,
  // runs it, and reacts to a 401/403 by logging out before rethrowing.
  request: <T>(fn: (token: string) => Promise<T>) => Promise<T>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

function isAuthFailure(err: unknown): boolean {
  return err instanceof ApiError && err.kind === 'rejected' && (err.status === 401 || err.status === 403);
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>('restoring');
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getToken()
      .then((restored) => {
        if (cancelled) return;
        setToken(restored);
        setStatus(restored ? 'authenticated' : 'unauthenticated');
      })
      .catch(() => {
        // A storage backend that is unavailable (never a native build) must
        // still resolve the splash -- treat it as "no session", not a hang.
        if (!cancelled) setStatus('unauthenticated');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (newToken: string) => {
    await saveToken(newToken);
    setToken(newToken);
    setStatus('authenticated');
  }, []);

  const logout = useCallback(async () => {
    await clearToken();
    setToken(null);
    setStatus('unauthenticated');
  }, []);

  const request = useCallback(
    async <T,>(fn: (currentToken: string) => Promise<T>): Promise<T> => {
      if (!token) {
        await logout();
        throw new ApiError('rejected', 'No active session.', 401);
      }
      try {
        return await fn(token);
      } catch (err) {
        if (isAuthFailure(err)) {
          await logout();
        }
        throw err;
      }
    },
    [token, logout]
  );

  const value = useMemo<SessionContextValue>(
    () => ({ status, login, logout, request }),
    [status, login, logout, request]
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) {
    throw new Error('useSession() called outside a SessionProvider');
  }
  return ctx;
}
