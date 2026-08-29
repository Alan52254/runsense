/* One coherent icon language for RunSense.
 * Phosphor supplies purpose-built running, training, health, and coaching
 * symbols instead of generic sparkle/plus/gauge shorthand. */

import {
  ArrowsClockwise,
  CalendarBlank,
  CaretDown,
  CaretRight,
  CaretUp,
  ChartLineUp,
  ChatCircleText,
  Check,
  ClipboardText,
  Cloud,
  DownloadSimple,
  FirstAidKit,
  Gauge,
  GearSix,
  Heartbeat,
  House,
  Info,
  LinkSimple,
  ListChecks,
  LockKey,
  MagnifyingGlass,
  Moon,
  PersonSimpleRun,
  Plus,
  Pulse,
  ShieldCheck,
  SignOut,
  SneakerMove,
  Sun,
  Trash,
  Translate,
  UsersThree,
  Warning,
  WifiSlash,
  X,
} from "@phosphor-icons/react";
import type { Icon as PhosphorIcon, IconWeight } from "@phosphor-icons/react";

export type IconName =
  | "activity"
  | "alert"
  | "assignment"
  | "body-status"
  | "calendar"
  | "check"
  | "chevron-down"
  | "chevron-right"
  | "chevron-up"
  | "cloud"
  | "coach-note"
  | "download"
  | "gauge"
  | "heart"
  | "history"
  | "home"
  | "info"
  | "link"
  | "lock"
  | "logout"
  | "moon"
  | "plus"
  | "refresh"
  | "runner"
  | "search"
  | "settings"
  | "shield"
  | "shoe"
  | "sun"
  | "trash"
  | "trend"
  | "translate"
  | "users"
  | "wifi-off"
  | "x";

const ICONS: Record<IconName, PhosphorIcon> = {
  activity: Pulse,
  alert: Warning,
  assignment: ClipboardText,
  "body-status": FirstAidKit,
  calendar: CalendarBlank,
  check: Check,
  "chevron-down": CaretDown,
  "chevron-right": CaretRight,
  "chevron-up": CaretUp,
  cloud: Cloud,
  "coach-note": ChatCircleText,
  download: DownloadSimple,
  gauge: Gauge,
  heart: Heartbeat,
  history: ListChecks,
  home: House,
  info: Info,
  link: LinkSimple,
  lock: LockKey,
  logout: SignOut,
  moon: Moon,
  plus: Plus,
  refresh: ArrowsClockwise,
  runner: PersonSimpleRun,
  search: MagnifyingGlass,
  settings: GearSix,
  shield: ShieldCheck,
  shoe: SneakerMove,
  sun: Sun,
  trash: Trash,
  trend: ChartLineUp,
  translate: Translate,
  users: UsersThree,
  "wifi-off": WifiSlash,
  x: X,
};

interface IconProps {
  name: IconName;
  size?: number;
  className?: string;
  strokeWidth?: number;
  weight?: IconWeight;
}

export function Icon({
  name,
  size = 18,
  className,
  strokeWidth = 1.6,
  weight,
}: IconProps) {
  const Glyph = ICONS[name];
  return (
    <Glyph
      className={className}
      size={size}
      weight={weight ?? (strokeWidth >= 2 ? "bold" : "regular")}
      aria-hidden="true"
      focusable="false"
    />
  );
}
