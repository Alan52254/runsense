/* A small hand-picked icon set. 1.6px stroke, 24px viewBox, currentColor —
 * so an icon inherits whatever text token its container uses. */

export type IconName =
  | "activity"
  | "alert"
  | "calendar"
  | "check"
  | "chevron-right"
  | "cloud"
  | "download"
  | "gauge"
  | "heart"
  | "home"
  | "info"
  | "link"
  | "lock"
  | "logout"
  | "moon"
  | "plus"
  | "refresh"
  | "search"
  | "settings"
  | "shield"
  | "sparkle"
  | "sun"
  | "trash"
  | "users"
  | "wifi-off"
  | "x";

const PATHS: Record<IconName, string> = {
  activity: "M3 12h4l3 8 4-16 3 8h4",
  alert: "M12 9v4M12 17h.01M10.3 3.9 2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z",
  calendar: "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z",
  check: "m20 6-11 11-5-5",
  "chevron-right": "m9 18 6-6-6-6",
  cloud: "M17.5 19a4.5 4.5 0 0 0 .3-9 6.5 6.5 0 0 0-12.6 1.6A3.8 3.8 0 0 0 6 19h11.5Z",
  download: "M12 3v12m0 0 4-4m-4 4-4-4M4 18v1a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-1",
  gauge: "M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm1.5-3.5L18 6M3.5 18a9 9 0 1 1 17 0",
  heart: "M12 20s-7.5-4.6-7.5-10A4.5 4.5 0 0 1 12 7.5 4.5 4.5 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10Z",
  home: "M3 10.5 12 3l9 7.5M5.5 9.5V20a1 1 0 0 0 1 1h4v-6h3v6h4a1 1 0 0 0 1-1V9.5",
  info: "M12 16v-5M12 8h.01M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z",
  link: "M10 13a4 4 0 0 0 5.7.4l3-3a4 4 0 0 0-5.7-5.7l-1.5 1.5M14 11a4 4 0 0 0-5.7-.4l-3 3a4 4 0 0 0 5.7 5.7l1.5-1.5",
  lock: "M7 11V8a5 5 0 0 1 10 0v3M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1Z",
  logout: "M15 17l5-5-5-5M20 12H9M12 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h6",
  moon: "M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5Z",
  plus: "M12 5v14M5 12h14",
  refresh: "M20 11A8 8 0 0 0 6.3 6.3L4 8.5M4 5v3.5h3.5M4 13a8 8 0 0 0 13.7 4.7L20 15.5M20 19v-3.5h-3.5",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm10 2-4.3-4.3",
  settings:
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.5-2-3.4-2.3 1a7.5 7.5 0 0 0-2-1.2L14.6 2h-4l-.4 2.6a7.5 7.5 0 0 0-2 1.2l-2.3-1-2 3.4 2 1.5a7.4 7.4 0 0 0 0 2.5l-2 1.5 2 3.4 2.3-1a7.5 7.5 0 0 0 2 1.2l.4 2.6h4l.4-2.6a7.5 7.5 0 0 0 2-1.2l2.3 1 2-3.4-2-1.5c.06-.4.1-.8.1-1.2Z",
  shield: "M12 21s7-3.2 7-9V5.8L12 3 5 5.8V12c0 5.8 7 9 7 9Z",
  sparkle: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3ZM18.5 16l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10ZM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  trash: "M4 7h16M10 11v6M14 11v6M5 7l1 13a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1l1-13M9 7V4h6v3",
  users: "M16 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm13 10v-2a4 4 0 0 0-3-3.9M16 2.1a4 4 0 0 1 0 7.8",
  "wifi-off": "M2 3l19 19M8.5 16.4a5 5 0 0 1 7 0M5 12.9a10 10 0 0 1 4-2.5M2 9.5a15 15 0 0 1 4-2.6M12 20h.01M19 12.9a10 10 0 0 0-3.4-2.3M22 9.5a15 15 0 0 0-8.5-3.4",
  x: "M6 6l12 12M18 6 6 18",
};

interface IconProps {
  name: IconName;
  size?: number;
  className?: string;
  strokeWidth?: number;
}

export function Icon({ name, size = 18, className, strokeWidth = 1.6 }: IconProps) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
