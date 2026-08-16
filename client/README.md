# RunSense client sync package -- manual-workout-create-sync

Local durable persistence (`LocalActivityStore`, SQLite-backed via Node's
built-in `node:sqlite`) and the offline-first sync coordinator
(`SyncCoordinator`) for manual workout entries. No UI here -- this is the
storage + sync engine a future app shell (React Native, per the SRS's tech
choice) calls into. See
`openspec/changes/manual-workout-create-sync/` for the governing spec.

## Setup

```bash
npm install
```

## Running tests

```bash
npm test        # node --test tests/*.test.ts
npm run typecheck
```

Tests run against real on-disk SQLite files (via a temp directory) and a
fake in-memory API client (`tests/fakeApiClient.ts`) that faithfully
reproduces the real endpoint's idempotency contract -- no server or
database required.

## Why `node --test` instead of a bundler-based runner

`node:sqlite` is a Node built-in not yet recognized by Vite's bundled list
of Node builtins, which broke Vitest's transform step. Since Node 22+ runs
TypeScript natively (type-stripping, no bundler), this package's source
and tests use `.ts` extensions directly and run unbundled via `node --test`.
Constructors avoid TS parameter-property shorthand (`constructor(private
readonly x: T)`) because Node's strip-only mode doesn't support syntax with
runtime semantics beyond type erasure.
