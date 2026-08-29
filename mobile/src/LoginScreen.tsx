import { useState } from 'react';
import {
  ActivityIndicator,
  Button,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { ApiError, demoLogin } from './api';
import { useSession } from './SessionContext';

const DEMO_ACCOUNTS = [
  { label: '🇹🇼 臺北 (Taipei)', email: 'runner.taipei@runsense.demo', password: 'TaipeiDemo!2026' },
  { label: '🇯🇵 東京 (Tokyo)', email: 'runner.tokyo@runsense.demo', password: 'TokyoDemo!2026' },
  { label: '🇬🇧 倫敦 (London)', email: 'runner.london@runsense.demo', password: 'LondonDemo!2026' },
];

export default function LoginScreen() {
  const { login } = useSession();
  const [email, setEmail] = useState('runner.taipei@runsense.demo');
  const [password, setPassword] = useState('TaipeiDemo!2026');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(customEmail?: string, customPass?: string) {
    const loginEmail = customEmail ?? email;
    const loginPass = customPass ?? password;
    setError(null);
    setIsSubmitting(true);
    try {
      const result = await demoLogin(loginEmail, loginPass);
      await login(result.access_token);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.kind === 'network' ? 'Network error -- could not reach backend at 10.0.2.2:8000.' : err.message);
      } else {
        setError('Something went wrong.');
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  function selectPersona(p: typeof DEMO_ACCOUNTS[0]) {
    setEmail(p.email);
    setPassword(p.password);
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>RunSense</Text>
      <Text style={styles.subtitle}>Competition Demo Login</Text>

      {/* Quick 1-Tap Persona Selector */}
      <View style={styles.personaRow}>
        {DEMO_ACCOUNTS.map((p) => (
          <TouchableOpacity
            key={p.email}
            style={[styles.personaChip, email === p.email && styles.personaChipActive]}
            onPress={() => selectPersona(p)}
          >
            <Text style={[styles.personaText, email === p.email && styles.personaTextActive]}>
              {p.label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <TextInput
        style={styles.input}
        placeholder="Email"
        autoCapitalize="none"
        keyboardType="email-address"
        value={email}
        onChangeText={setEmail}
      />
      <TextInput
        style={styles.input}
        placeholder="Password"
        secureTextEntry
        value={password}
        onChangeText={setPassword}
      />

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {isSubmitting ? (
        <ActivityIndicator size="large" color="#ea580c" />
      ) : (
        <TouchableOpacity
          style={[styles.loginBtn, (!email || !password) && styles.loginBtnDisabled]}
          onPress={() => handleSubmit()}
          disabled={!email || !password}
        >
          <Text style={styles.loginBtnText}>登入 (LOG IN)</Text>
        </TouchableOpacity>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', padding: 24, gap: 12, backgroundColor: '#f8fafc' },
  title: { fontSize: 32, fontWeight: '800', textAlign: 'center', color: '#0f172a' },
  subtitle: { fontSize: 14, color: '#64748b', textAlign: 'center', marginBottom: 10 },
  personaRow: { flexDirection: 'row', justifyContent: 'space-between', gap: 6, marginBottom: 8 },
  personaChip: {
    flex: 1,
    paddingVertical: 8,
    paddingHorizontal: 4,
    borderRadius: 8,
    backgroundColor: '#e2e8f0',
    alignItems: 'center',
  },
  personaChipActive: { backgroundColor: '#ea580c' },
  personaText: { fontSize: 11.5, fontWeight: '600', color: '#475569' },
  personaTextActive: { color: '#ffffff' },
  input: {
    borderWidth: 1,
    borderColor: '#cbd5e1',
    backgroundColor: '#ffffff',
    borderRadius: 10,
    padding: 14,
    fontSize: 15,
  },
  error: { color: '#dc2626', textAlign: 'center', fontSize: 13 },
  loginBtn: {
    backgroundColor: '#ea580c',
    paddingVertical: 14,
    borderRadius: 10,
    alignItems: 'center',
    marginTop: 6,
  },
  loginBtnDisabled: { backgroundColor: '#94a3b8' },
  loginBtnText: { color: '#ffffff', fontSize: 16, fontWeight: '700' },
});
