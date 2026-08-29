import { Platform } from 'react-native';

// In Android Emulator, localhost maps to the emulator device itself.
// 10.0.2.2 is the special alias to reach the host computer (where backend runs on :8000).
const defaultHost = Platform.OS === 'android' ? 'http://10.0.2.2:8000' : 'http://localhost:8000';

export const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_BASE_URL ?? defaultHost;
