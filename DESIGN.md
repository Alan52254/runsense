---
name: RunSense
description: Obsidian glass, kinetic orange, climate cyan. A 3-second departure decision with the science one drawer away.
colors:
  void: "#111923"
  surface-1: "#192433"
  surface-2: "#151f2c"
  surface-3: "#233246"
  border-glass: "rgba(160, 185, 220, 0.14)"
  border-glass-strong: "rgba(170, 195, 230, 0.3)"
  border-active: "rgba(255, 107, 0, 0.4)"
  kinetic-orange: "#ff6b00"
  kinetic-orange-light: "#ff9e44"
  orange-ink: "#ffad70"
  orange-glow: "rgba(255, 107, 0, 0.35)"
  climate-cyan: "#00e5ff"
  climate-glow: "rgba(0, 229, 255, 0.3)"
  safety-green: "#00f5a0"
  safety-glow: "rgba(0, 245, 160, 0.25)"
  alert-red: "#ff3b30"
  alert-glow: "rgba(255, 59, 48, 0.4)"
  warning-amber: "#f5c04a"
  text-primary: "#f8fafc"
  text-secondary: "#cbd5e1"
  text-quiet: "#94a3b8"
  text-muted: "#8a9ab0"
  on-orange: "#18100a"
typography:
  display:
    fontFamily: "Noto Sans TC, PingFang TC, Microsoft JhengHei, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(28px, 4vw, 40px)"
    fontWeight: 700
    lineHeight: 1.15
  headline:
    fontFamily: "Noto Sans TC, PingFang TC, Microsoft JhengHei, Segoe UI, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 700
    lineHeight: 1.3
  title:
    fontFamily: "Noto Sans TC, PingFang TC, Microsoft JhengHei, Segoe UI, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 700
  body:
    fontFamily: "Noto Sans TC, PingFang TC, Microsoft JhengHei, Segoe UI, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontFamily: "Noto Sans TC, PingFang TC, Microsoft JhengHei, Segoe UI, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 500
  figure:
    fontFamily: "Barlow Condensed, Noto Sans TC, sans-serif"
    fontSize: "clamp(26px, 3.4vw, 36px)"
    fontWeight: 700
    lineHeight: 1.1
    fontFeature: "tnum"
  led:
    fontFamily: "Share Tech Mono, ui-monospace, Cascadia Code, Consolas, monospace"
    fontSize: "26px"
    fontWeight: 400
    letterSpacing: "0.06em"
rounded:
  sm: "8px"
  inner: "16px"
  outer: "24px"
  pill: "999px"
spacing:
  s1: "4px"
  s2: "8px"
  s3: "12px"
  s4: "16px"
  s5: "20px"
  s6: "24px"
  s8: "32px"
  s10: "40px"
  s12: "48px"
components:
  button-primary:
    backgroundColor: "{colors.kinetic-orange}"
    textColor: "{colors.on-orange}"
    rounded: "{rounded.outer}"
    height: "40px"
    padding: "0 16px"
  button-cta-hero:
    backgroundColor: "{colors.kinetic-orange}"
    textColor: "{colors.on-orange}"
    rounded: "{rounded.inner}"
    height: "48px"
    padding: "0 24px"
  button-secondary:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.outer}"
    height: "40px"
    padding: "0 16px"
  button-ghost:
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.outer}"
    height: "40px"
  glass-panel:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.outer}"
    padding: "20px"
  glass-inner-card:
    backgroundColor: "{colors.surface-2}"
    rounded: "{rounded.inner}"
    padding: "12px 16px"
  climate-pill:
    textColor: "{colors.climate-cyan}"
    rounded: "{rounded.pill}"
    height: "32px"
    padding: "4px 12px"
  nav-item:
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.inner}"
    height: "40px"
    padding: "0 12px"
  nav-item-active:
    textColor: "{colors.kinetic-orange}"
    rounded: "{rounded.inner}"
  input:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text-primary}"
    rounded: "10px"
    height: "44px"
    padding: "0 12px"
---

# Design System: RunSense

Recorded from the shipped build on `feat/frontend-redesign` (dark theme). Governing brief: `.scratch/frontend-redesign-v2/reference.md` (v2, 2026-10-22). The earlier "race-course signage" direction is superseded and is not the system. The light theme is functional on the same tokens but has not been redesigned; do not extend it.

## Overview

**Creative North Star: "The Night Run Dashboard"**

Dark frosted glass floating on a flat obsidian void. Everything secondary lives in a live ticker or a drawer, so the canvas shows one thing: today's departure decision. Depth tells clickable control layers (tilting hero, lifting rail stages, sliding drawers) from background reference (flat hairline tables and quiet text).

Light is scarce on purpose. Orange and glow mark the decision and the focus, cyan marks climate, green and red mark safety state. Everything else is neutral glass, so when something glows it means something.

**Key Characteristics:**
- Three layers of disclosure: ticker and hero, rail, right drawers.
- Large continuous radii: 24px containers, 16px interactive cards.
- Condensed tabular numerals for every glanceable figure.
- Real data only; the product never shows a figure it cannot trace to the athlete's records.

## Colors

Deep blue-grey ground (main's family: #111923 void, #192433 / #151f2c / #233246 surfaces), one warm accent, two functional hues, and semantic safety colours. Values are in the frontmatter (dark theme); roles below. Code reads them through `--bg-void`, `--bg-surface-1..3`, `--brand-primary`, `--climate-cyan`, `--safety-green`, `--alert-red`, `--text-primary/-secondary/-muted`.

- **Void and surfaces** (`void`, `surface-1..3`): void is the page ground; glass panels are surface-1 at 62% over it, inner cards surface-2 at 55%, hovered or open rows use a white fill at 4% / 8%.
- **Kinetic Orange** (`kinetic-orange` to `kinetic-orange-light`, 135deg gradient): the brand. Gradient fill only on the primary CTA. As text on dark use `orange-ink` or the brand orange (`--active-ink`), never the dark-theme gradient.
- **Climate Cyan**: the climate-equivalent pace pill, weather and environment rows, the focus ring, and chart series 1. Nothing else.
- **Safety Green / Alert Red / Warning Amber**: triage state (clear, red flag), ACWR chip zone, connection state, badges. Always paired with words or icons, never colour alone.
- **Text**: primary for content, secondary (`#cbd5e1`) for supporting copy, muted (`#8a9ab0`, lifted from the spec's `#64748B` to clear 4.5:1 at 12px) for captions only.

### Named Rules

**The Earned Glow Rule.** Gradient and glow appear only on: the hero decision card (border, ambient glow, pointer specular), the primary CTA, the logo and LED digits, and the focused or active state (active nav row, focused rail stage, selected ranking row). Alert glow additionally marks a live red-flag triage panel. Not on ordinary cards, buttons, table rows, or borders.

**The One Verdict Rule.** Colour states what the data supports and no more. The ACWR chip names its zone in words; load is never a traffic-light verdict.

**The Cyan Means Weather Rule.** Cyan is climate and focus only. Do not use it as a second brand accent.

## Typography

**Body and display:** Noto Sans TC with PingFang TC, Microsoft JhengHei, Segoe UI, system-ui fallbacks. Noto Sans TC is named but not bundled, so on machines without it the CJK fallback renders; Traditional Chinese first, English second.
**Figures:** Barlow Condensed (500/700/800, bundled via fontsource) with tabular numerals, for every number read at a glance.
**LED:** Share Tech Mono (bundled), only for the wordmark and live or clock digits.
**Code and identifiers:** Cascadia Code stack (`--font-mono`).

**Character:** a calm CJK text face with a sporty condensed numeral and one display-segment voice for the logo.

### Hierarchy
- **Hero title** (700, `clamp(28px, 4vw, 40px)`, 1.15): today's workout name. Rest or empty hero: `clamp(20px, 2.6vw, 26px)`.
- **Hero metrics** (Barlow 700, `clamp(26px, 3.4vw, 36px)`): duration, distance, target pace.
- **Drawer or panel title** (700, 16 to 20px).
- **Body** (400, 14px, 1.65): insight text, panel copy. Cap prose at about 62 to 70ch.
- **Label and meta** (13px): ticker items, key-value rows, sub-copy. 12px is the floor, used for table headers, rank meta, slot labels.
- **Page title** in the top bar: 18px bold. A screen heading that duplicates it is visually hidden but kept for assistive tech.
- Scale tokens: `--fs-12/13/14/16/20/28`, weights 400/500/700. Tables use Barlow at 20px for numeric cells.

### Named Rules

**The 12px Floor Rule.** Nothing under 12px, ever. CJK needs it.

**The Figure Rule.** Numbers that answer a question (pace, distance, ACWR, score) use the condensed tabular face; running prose keeps the text face.

**The One LED Rule.** The LED face is for the logo and live digits only, not for headings or labels.

## Layout

App shell: a 248px glass left rail and a main column, 12px apart on the void, inside a full-height grid. The main column is a 64px glass top bar (page title, ticker, actions) over a scrolling content area, max 1320px wide.

Spacing is a 4px scale (`--s-1..s-12`); panels pad 20px (16px under 600px), hero pads 24px, gaps between panels 20px.

### Three layers (the IA)
1. **Ticker and hero** (always visible). The ticker sits in the top bar and collects secondary live state. The hero is today's decision: workout, duration, distance, target pace, a cyan climate-equivalent pace pill, the 系統建議 / 教練安排 toggle, an ACWR safe-zone chip, and one-tap actions (開始跑步 as the single CTA, 身體回報, switch to coach plan).
2. **Rail**. Warm-up, main set and cool-down as an overlapped horizontal rail that slides apart on hover or focus; the focused stage shows pace and heart-rate range.
3. **Right drawers**. 7 and 28 day load (ACWR), per-rep interval analysis, environment details, the AI health coach. Hidden until asked; never cover the decision layer by default.

Dashboard is a two-column grid: main (hero, rail) plus a 340px side column (safety triage panel, coach-insight preview linking to the load drawer, recent runs). Below 1100px it stacks. Below 600px: glass padding shrinks, hero actions go full-width and stacked, rail stacks vertically with details always visible, drawers go full-width with square corners, and the athlete gets a bottom tab bar (今日 / 課表 / 跑步 / 歷程 plus 更多).

Navigation has three layers of IA by workspace: the athlete nav (training: dashboard, coach plan, live run, log, history, load, body, 健康教練, method; account: team, settings) and the coach nav (team overview, schedule review, assignments, 健康教練). 健康教練 is both a left-nav page and the header drawer, sharing one conversation; on the page the header button states where you are instead of opening a second copy.

## Elevation & Depth

Hybrid: tonal glass layers plus soft ambient shadow, with real 3D only on the hero.

- **Glass** (`backdrop-filter: blur(20px) saturate(140%)`, 1px `border-glass`): shell rail, top bar, panels.
- **Panel shadow** (`0 16px 40px rgba(0,0,0,0.45)`): outer containers only; inner cards have none.
- **Drawer** (blur 24px, 90% surface-1, shadow `-16px 0 48px rgba(0,0,0,0.45)`, scrim blurred 6px).
- **Hero glow** (`0 0 40px -12px` brand glow over the panel shadow, border `border-active`).
- **Active ring** (`0 0 0 1px border-active, 0 6px 22px rgba(255,107,0,0.22)`): active nav row, focused rail stage, selected row.
- **CTA glow** (`0 8px 28px` brand glow, rising to `0 10px 34px` on hover).
- **Alert glow** (`0 0 28px -8px` alert glow): triage panel while a red flag exists.

### Named Rules

**The Depth Means Control Rule.** Tilt, lift and slide mark things you can press or open. Reference content (tables, hairline lists, explanations) stays flat.

**The No Card-in-Card Rule.** A card does not sit inside a card; inside a panel use inner glass (16px) or hairline rows.

## Shapes

Large continuous corners. Outer containers 24px; inner interactive cards, nav rows, rail stages and the hero CTA 16px; small chips and rows inside drawers 8px; pills and ticker 999px. Buttons use the 24px token. Borders are 1px hairlines at 8% white (20% on outlined controls and inputs, which need more than a hairline to read). Inputs are 44px tall with a 10px radius. Drawers round only their left edge (24px) and are square on phones.

## Components

Icons are Phosphor line icons through `components/Icon.tsx`. No emoji, no glyph icons, anywhere (including the ticker).

### Buttons
- **Primary:** brand gradient, dark ink, bold, glow. One per view. Hero CTA is 48px at 16px radius.
- **Secondary:** glass fill with a stronger border; the default.
- **Ghost:** transparent, secondary text; icon buttons and menu rows.
- **Danger:** solid alert red, white text, for destructive confirms only.
- Sizes 32 / 40 / 48px. Disabled is 45% opacity with no glow. Primary focus ring is drawn inside the fill.

### GlassPanel (`motion.tsx`)
`variant="outer"` (24px, shadow) for page panels; `variant="inner"` (16px, lighter fill) for cards on a panel. Padding sm 12 / md 20 / lg 24.

### TiltCard
The hero only. Spring 400/30, perspective 1000px, max 8deg per axis, scale 1.01, orange specular `radial-gradient(circle 350px ...)` following the pointer, children may lift with `.tilt-layer` (translateZ 32px). Static for coarse pointers and reduced motion.

### Rail
Overlapped stages (-32px) that slide apart (+12px gap) on hover or focus, spring 350/25. Focused stage: y -6, scale 1.02, active ring, detail row opens. Others: opacity 0.6, scale 0.96. Arrow keys move focus. Use for ordered stages of one session, not general lists.

### SlideOver
Right drawer, sizes md 560 / lg 960 / xl 1040px. Spring 0.4s, no bounce; scrim fades in 240ms. Page behind is inert, Tab is trapped, Esc and scrim click close, focus returns to the opener. Use for layer 3 detail, never for a primary action path.

### Ticker
Pill strip in the top bar. Items are icon plus words (icon tone: neutral, climate, safe, alert, brand). Shell always supplies connection and sync; a screen adds weather, ACWR, triage with `useShellTicker`. It scrolls only when items overflow (about 6s per item, min 24s), pauses on hover and focus, and the info button opens environment details.

### Climate pill, ACWR chip
Cyan-tinted pill with the equivalent pace in Barlow; ACWR chip names the zone in words with green (safe), orange (high) or red (alert) border.

### Triage panel
Green outline when clear; red outline, icon and alert glow when a red flag exists. State is stated in words.

### Navigation
40px rows, 16px radius, icon plus label. Active: filled glass, brand-orange text, glowing edge. Never a vertical stripe. Count badges are orange pills with dark ink.

### Cards, tables, fields
`.card` is a quiet glass sheet with a hairline border. Data tables are hairline (rules only, no fills); on phones rows stack into labelled lines. Switch, segmented control (`aria-pressed`), notice (neutral, accent, warning, critical), empty state and modal follow the same glass tokens. Badges use the soft tone pairs (good, warning, serious, critical).

### Coach chat
One panel in two frames (drawer and page). Coach words set as text; user messages are a tinted bubble with 16px radius and a tight lower-right corner. Citations and tool steps sit under the reply.

## States

- **Hover:** glass fill 4% to 8%, border to muted; no scale except hero tilt and rail.
- **Focus:** `:focus-visible` 2px cyan ring, 2px offset (hero CTA uses a text-colour ring at 3px offset; primary buttons draw it inside).
- **Active/selected:** active ring (orange edge plus soft glow).
- **Loading and working:** a spinner and "working" copy; the LED pulse dot blinks by opacity only.
- **Empty:** icon, title, one line of description, optional action; never a blank panel.
- **Unauthorised data:** 未授權, never blank.
- **Offline:** ticker shows offline with an alert-toned icon; the topbar toggle changes `aria-pressed`; pending sync counts show on 歷程 and the sync button.
- **Error:** field errors in alert text under the field; notices use the critical tone with an icon.
- **Disabled:** 45% opacity, not-allowed cursor, no glow.

## Motion

Framer Motion supplies springs, tilt and slides only; everything else is CSS. Constants live in `components/motion.tsx`: `SPRING_TILT` 400/30, `SPRING_RAIL` 350/25, `SPRING_DRAWER` 0.4s bounce 0. CSS tokens: `--ease-out` cubic-bezier(0.16, 1, 0.3, 1), fast 140ms, medium 240ms, slide 400ms.

Reduced motion (`prefers-reduced-motion`): tilt is static, the ticker stops and its items wrap, the rail has no springs or transitions, drawers appear with an instant opacity fade, CTA hover lift is off. Tilt also needs `(pointer: fine)` and a mouse.

## Accessibility floor

Text at least 12px; visible focus everywhere; colour never alone (words or icons accompany every state); drawers are dialogs with `aria-labelledby`, trapped focus, Esc; the ticker is a labelled region; rail is an ordered list with a label and arrow-key support; tap targets 32px minimum (44px for chat close and phone review actions); muted text meets 4.5:1.

## Wording

- "AI", "Llama 3.1", "ACWR", "Triage" are allowed on screen. Other banned interface vocabulary stays enforced by `lib/interfaceVocabulary.test.ts`.
- No emoji.
- The team-chat mention shows as **@助手** and is sent as **@AI** (`lib/assistantMention.ts`); both are accepted when typed.
- Use real app data in every example and screen, never illustrative numbers from the brief.
- Traditional Chinese first; English strings come from `LocaleContext`.

### Demo-script controls (wording and behaviour are frozen)
傳給教練, 套用到… (套用到今天 / 套用到 yyyy-mm-dd), 依此排課, 產生草案, 開啟, 修改, 確認並排給選手, 分析這次訓練. Do not rename, reorder behind menus, or hide these; the recording script clicks them by text.

## Do's and Don'ts

### Do:
- **Do** keep one primary CTA per view and let the hero card be the only glowing, tilting surface.
- **Do** put detail in a SlideOver and keep the dashboard answerable in three seconds.
- **Do** use `--fs-*`, `--s-*`, `--r-*` and colour tokens; add no new raw hex in components.
- **Do** pair every colour state with words or an icon.
- **Do** use Phosphor icons through `Icon`.

### Don't:
- **Don't** mark the active nav item with a vertical stripe.
- **Don't** add glow, gradient or tilt to ordinary cards, buttons or borders.
- **Don't** nest a card inside a card.
- **Don't** use emoji or glyph icons, including in the ticker.
- **Don't** show a health verdict the data cannot support.
- **Don't** document or reintroduce the race-course signage world (km-marker plates, signage palette).

## Known drift (observed in the build, not canonized)

- **Eyebrow and kicker-style labels:** `.ath-eyebrow` (hero), wide-tracked muted labels in `.nav-section-label` (0.14em) and `.module-title` (0.12em), and `.analysis-next-tag`. A craft-floor refusal; do not copy for new surfaces.
- **Race-course leftovers:** `Plate` and hairline modules (`primitives.css`, still used by `workoutAnalysis.tsx`), `--plate-*` tokens and the `.card` comment about "blue". The hairline table and list are current; the km-marker plate is not.
- **Hard-coded values** in `coach-chat.css` (16px and 24px radii, a 66px offset) and `.input` 10px radius, not on the radius tokens.
- Legacy alias tokens (`--surface`, `--text-2`, `--accent`, etc.) remain for compatibility; prefer the v2 names.


## User refinement ? 2026-10-23

Restore the runner line mark and plain RunSense wordmark. Navigation uses a solid navy rail with quiet blue selection, recalling the original application shell. Sidebar owns navigation: dashboard omits duplicate body-report and manual-log actions, keeping the start-run action. Ranked alternatives, upcoming assignments, recent runs and report details use progressive disclosure. Empty body reports never imply safety. Icons remain a consistent functional line family; avoid decorative sparkle or model symbolism.
