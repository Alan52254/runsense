import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { StatusBar } from 'expo-status-bar';
import { ActivityIndicator, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { SessionProvider, useSession } from './src/SessionContext';
import LoginScreen from './src/LoginScreen';
import DashboardScreen from './src/DashboardScreen';
import HistoryScreen from './src/HistoryScreen';
import BodyScreen from './src/BodyScreen';
import TrendScreen from './src/TrendScreen';
import LiveRunScreen from './src/LiveRunScreen';
import LogWorkoutScreen from './src/LogWorkoutScreen';
import MethodScreen from './src/MethodScreen';
import { colors } from './src/theme';

const AuthStack = createNativeStackNavigator();
const AppStack = createNativeStackNavigator();
const Tabs = createBottomTabNavigator();

function AuthenticatedTabs() {
  return (
    <Tabs.Navigator screenOptions={({ route }) => ({
      headerShown: false,
      tabBarActiveTintColor: colors.accent,
      tabBarInactiveTintColor: '#8FA2B3',
      tabBarStyle: { backgroundColor: colors.nav, borderTopColor: '#223242', height: 62 },
      tabBarLabelStyle: { fontSize: 11, fontWeight: '600', paddingBottom: 5 },
      tabBarIcon: ({ color, size, focused }) => {
        const names: Record<string, keyof typeof Ionicons.glyphMap> = {
          Today: focused ? 'speedometer' : 'speedometer-outline',
          History: focused ? 'time' : 'time-outline',
          Body: focused ? 'body' : 'body-outline',
          Trend: focused ? 'analytics' : 'analytics-outline',
        };
        return <Ionicons name={names[route.name]} size={size} color={color} />;
      },
    })}>
      <Tabs.Screen name="Today" component={DashboardScreen} />
      <Tabs.Screen name="History" component={HistoryScreen} />
      <Tabs.Screen name="Body" component={BodyScreen} />
      <Tabs.Screen name="Trend" component={TrendScreen} />
    </Tabs.Navigator>
  );
}

function AuthenticatedStack() {
  return (
    <AppStack.Navigator>
      <AppStack.Screen name="Tabs" component={AuthenticatedTabs} options={{ headerShown: false }} />
      <AppStack.Screen name="LiveRun" component={LiveRunScreen} options={{ title: '出發開跑！' }} />
      <AppStack.Screen name="LogWorkout" component={LogWorkoutScreen} options={{ title: '手動補登' }} />
      <AppStack.Screen name="Method" component={MethodScreen} options={{ title: '方法與依據' }} />
    </AppStack.Navigator>
  );
}

function UnauthenticatedStack() {
  return (
    <AuthStack.Navigator screenOptions={{ headerShown: false }}>
      <AuthStack.Screen name="Login" component={LoginScreen} />
    </AuthStack.Navigator>
  );
}

// Switches navigators on session status. An explicit "restoring" status
// (SessionContext.tsx) means an absent token is never mistaken for "not
// logged in" during the async secure-storage read -- no login flash.
function RootNavigator() {
  const { status } = useSession();

  if (status === 'restoring') {
    return (
      <SafeAreaView style={styles.centered}>
        <ActivityIndicator />
      </SafeAreaView>
    );
  }

  return status === 'authenticated' ? <AuthenticatedStack /> : <UnauthenticatedStack />;
}

export default function App() {
  return (
    <SafeAreaProvider>
      <SessionProvider>
        <SafeAreaView style={styles.container} edges={['top', 'left', 'right']}>
          <StatusBar style="auto" />
          <NavigationContainer>
            <RootNavigator />
          </NavigationContainer>
        </SafeAreaView>
      </SessionProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.canvas },
  centered: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: colors.canvas },
});
