import { useState } from 'react';
import { Button, StyleSheet, Text, View } from 'react-native';
import { ApiError, setRestDay } from './api';
import { useSession } from './SessionContext';
import DateField from './DateField';

type ControlState =
  | { kind: 'idle' }
  | { kind: 'submitting' }
  | { kind: 'confirmed'; date: string }
  | { kind: 'revoked'; date: string }
  | { kind: 'conflict'; date: string }
  | { kind: 'error'; message: string };

// Rest is an explicit athlete action (spec.md "The App Never Infers Rest
// From Absence") -- this component only ever reflects a state the server
// has actually confirmed or revoked; there is no client-side guess.
export default function RestDayControl() {
  const { request } = useSession();
  const [date, setDate] = useState('');
  const [state, setState] = useState<ControlState>({ kind: 'idle' });

  async function submit(confirmed: boolean) {
    if (!date) return;
    setState({ kind: 'submitting' });
    try {
      const result = await request((token) => setRestDay(token, date, confirmed));
      setState(
        result.confirmed ? { kind: 'confirmed', date: result.date } : { kind: 'revoked', date: result.date }
      );
    } catch (err) {
      if (
        err instanceof ApiError &&
        err.status === 409 &&
        err.body &&
        typeof err.body === 'object' &&
        'error' in err.body &&
        (err.body as { error: unknown }).error === 'REST_DAY_CONFLICTS_WITH_ACTIVITY'
      ) {
        setState({ kind: 'conflict', date });
      } else if (err instanceof ApiError) {
        setState({ kind: 'error', message: err.message });
      } else {
        setState({ kind: 'error', message: 'Something went wrong.' });
      }
    }
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Rest Day</Text>
      <View style={styles.row}>
        <DateField value={date} onChangeText={setDate} />
        <Button title="Confirm Rest" onPress={() => submit(true)} disabled={!date} />
        <Button title="Revoke" onPress={() => submit(false)} disabled={!date} color="#888" />
      </View>

      {state.kind === 'confirmed' ? (
        <Text style={styles.status}>{state.date} confirmed as rest.</Text>
      ) : null}
      {state.kind === 'revoked' ? (
        <Text style={styles.status}>{state.date} rest confirmation revoked.</Text>
      ) : null}
      {state.kind === 'conflict' ? (
        <Text style={styles.error}>
          {state.date} already has a completed activity -- cannot confirm rest for it.
        </Text>
      ) : null}
      {state.kind === 'error' ? <Text style={styles.error}>{state.message}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { marginTop: 24, gap: 8 },
  title: { fontSize: 16, fontWeight: '600' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  status: { color: '#333' },
  error: { color: '#c00' },
});
