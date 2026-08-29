import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';

// Thin adapter over the OS-backed secure store (iOS Keychain / Android
// Keystore) -- see design.md Decision 1. Deliberately not AsyncStorage on
// native, which is unencrypted and does not satisfy REQ-AUTH-006's mobile
// clause. This module owns only the storage key name; session lifecycle
// (restore, login, logout, auth-failure handling) lives in SessionContext.tsx.
//
// On the web target (Expo web / react-native-web) `expo-secure-store` has no
// implementation and throws on first call. There is no OS keystore in a
// browser, so we fall back to localStorage there -- only ever exercised by the
// in-browser demo build, never by the shipped iOS/Android app.

const TOKEN_KEY = 'runsense.session.token';
const isWeb = Platform.OS === 'web';

function webGet(): string | null {
  try {
    return globalThis.localStorage?.getItem(TOKEN_KEY) ?? null;
  } catch {
    return null;
  }
}

export async function saveToken(token: string): Promise<void> {
  if (isWeb) {
    try {
      globalThis.localStorage?.setItem(TOKEN_KEY, token);
    } catch {
      /* private-mode / storage disabled: session simply won't persist */
    }
    return;
  }
  await SecureStore.setItemAsync(TOKEN_KEY, token);
}

export async function getToken(): Promise<string | null> {
  if (isWeb) return webGet();
  return SecureStore.getItemAsync(TOKEN_KEY);
}

export async function clearToken(): Promise<void> {
  if (isWeb) {
    try {
      globalThis.localStorage?.removeItem(TOKEN_KEY);
    } catch {
      /* nothing to clear */
    }
    return;
  }
  await SecureStore.deleteItemAsync(TOKEN_KEY);
}
