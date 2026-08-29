import * as SecureStore from 'expo-secure-store';

// Thin adapter over the OS-backed secure store (iOS Keychain / Android
// Keystore) -- see design.md Decision 1. Deliberately not AsyncStorage,
// which is unencrypted and does not satisfy REQ-AUTH-006's mobile clause.
// This module owns only the storage key name; session lifecycle (restore,
// login, logout, auth-failure handling) lives in SessionContext.tsx.

const TOKEN_KEY = 'runsense.session.token';

export async function saveToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(TOKEN_KEY, token);
}

export async function getToken(): Promise<string | null> {
  return SecureStore.getItemAsync(TOKEN_KEY);
}

export async function clearToken(): Promise<void> {
  await SecureStore.deleteItemAsync(TOKEN_KEY);
}
