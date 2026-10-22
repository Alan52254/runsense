# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary audience for this redesign: competition judges** (中技社科技創意競賽) who meet RunSense through a four-minute screen-recorded demo video. They see each screen for seconds, at video resolution, and must grasp what it does without reading fine print.
- **Users inside the product:** amateur and club runners (the Athlete workspace) and their coaches (the Coach workspace), Traditional Chinese (Taiwan) first, English available. Athletes check today's plan, log or review runs, report body status and ask the health coach; coaches review team status, approve weekly drafts and talk to athletes in team chat.

## Product Purpose

RunSense is an athlete-owned training and load platform. It records completed runs, shows 7-day and 28-day load honestly (no traffic-light verdicts), analyses interval sessions rep by rep against the coach's prescription, and lets a health coach and a team chat turn that data into next week's plan, which a human coach must approve before it reaches the athlete. Success for this redesign: in the demo video every screen reads at a glance and the product looks designed, not generated.

## Positioning

- The athlete owns the data; coaches see only what each athlete consents to, scope by scope, revocable at once.
- Numbers shown are traceable to the athlete's own records; the coach model must ground every figure in them.
- Prescriptions come from a deterministic rule engine and safety triage runs before any language model; the coach always has final say.

## Operating Context

- Demo flow recorded on video, desktop 1440 wide and phone 390 wide. The recording script clicks these exact controls, which must keep their wording and keep working: 傳給教練, 套用到…, 依此排課, 產生草案, 開啟, 修改, 確認並排給選手, 分析這次訓練.
- Data comes from Garmin-labelled demo personas (Tokyo athlete, London athlete, Taipei coach) in a local Postgres.
- Team chat uses an "@AI" mention to ask the assistant to turn a coach's message into a schedule card; it is being relabelled "@助手" on screen while "@AI" keeps working.

## Capabilities and Constraints

- Vite + React 19 + TypeScript under `web/`, hand-written CSS with design tokens, no UI kit, hand-drawn SVG charts.
- Dark theme is the one being redesigned now; the light theme stays functional on tokens and is redesigned later.
- The health coach must exist both as the header drawer and as a page in the left nav of both workspaces, sharing one conversation.

## Brand Commitments

- Name: RunSense (binding). Logo mark, orange, and dark-first are not binding.
- User-pinned visual constraints (2026-10-19): a clearer, more legible palette; a glow or neon quality on the logo and a few key moments is wanted; the active left-nav item must not be marked by a vertical stripe; remove the generic generated-dashboard look (gradient washes, card-everything, "AI" wording).

## Evidence on Hand

- Real demo data in the local database (activities, laps, load, analyses, chat). No testimonials, user counts or benchmarks exist; do not invent them.
- Current UI screenshots: scratchpad `shots/before/`.

## Product Principles

1. Lead with the answer: every analytic screen opens with its conclusion, detail on request.
2. Show only what can be traced to the athlete's data; never decorate a number with a verdict it cannot support.
3. The coach decides: system output is a draft until a person confirms it.
4. Consent is visible: unshared data says 未授權, never blank.

## Accessibility & Inclusion

- CJK text needs a higher size floor than Latin; nothing below 12px.
- Colour never carries meaning alone (pace and status also use words or icons).

## Current visual brief (2026-10-22)
User supplied v2 replaces the 2026-10-19 race-course palette: dark obsidian glass, kinetic orange, climate cyan, layered disclosure, subtle pointer tilt and sliding rails/drawers. Preserve all product truth above. Reference `.scratch/frontend-redesign-v2/reference.md`.
