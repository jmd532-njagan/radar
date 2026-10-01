# WatchTower changes made for RADAR

For whoever reviews and merges WatchTower's `feat-radar` branch into `main`. It lists every
change `feat-radar` makes to WatchTower, flags the files shared with non-RADAR features (those
need the closest review), and says what has to be configured and migrated for RADAR to work.

- **Repo / branch:** `jmangroup/watch-Tower`, branch `feat-radar` (all RADAR work; `main` is kept
  equal to upstream).
- **Last synced with `main`:** 2026-10-01 (merge of `origin/main` at `f59dd90` into `feat-radar`;
  see "Merge with main" below).
- **Size vs `main`:** about 75 files; most of it is new code under RADAR-only paths.
- **RADAR itself** is a separate FastAPI service (`jmd532-njagan/radar`). WatchTower hosts its UI,
  owns login, users, projects and integration credentials, and sends all email.

## 1. How the two connect

| Channel | Direction | Where in WatchTower |
|---|---|---|
| Failure intake | WatchTower → RADAR `POST /events/pipeline-failure`, HMAC-signed (`X-Radar-Signature-256`) | `src/lib/radar/notify-failure.ts`, `hmac.ts`, called from `src/app/api/data/index.ts` |
| Chat and admin API | Browser → WatchTower `/api/radar/*` → RADAR `/chat/*`, with a 90-second signed `X-Radar-Assertion` JWT naming the user | `src/app/api/radar/**`, `src/lib/radar/client.ts`, `assertion.ts`, `request-identity.ts` |
| Email | WatchTower only (RADAR never emails) | `src/lib/radar/radar-email.ts` (failure emails, memory-update emails) |

## 2. Configuration (`.env`)

| Variable | Value |
|---|---|
| `RADAR_API_BASE_URL` | RADAR's base URL (local: `http://localhost:8000`) |
| `RADAR_ASSERTION_SECRET` | Same value as RADAR's `RADAR_ASSERTION_SECRET`, at least 32 characters |
| `RADAR_WEBHOOK_SECRET` | Same value as RADAR's `HMAC_SECRET` |
| `JWT_SECRET_KEY` | Unchanged, but RADAR's `WATCHTOWER_CREDENTIAL_KEY` must equal it (RADAR decrypts integration secrets with it) |
| `AZURE_EMAIL_CONNECTION_STRING`, `AZURE_EMAIL_SENDER` | Needed for RADAR's emails (also used by main's alert emails) |

All are listed in `.env.example`.

## 3. Database (WatchTower's Prisma, `public` schema)

| Change | Migration |
|---|---|
| `UserProjectAssignment` table: manual project members for RADAR, with `notifyOnFailure` | earlier `feat-radar` commit (`aba8169`) |
| None of its own beyond that: RADAR reads main's `User.jinEmployeeId` and `credentialUser` (migration `20260925123354_constraints_added`, from `main`) | — |

RADAR's own tables live in a separate `radar` schema, migrated from the RADAR repo; nothing in
WatchTower's Prisma touches them.

Run `npx prisma migrate deploy` and `npx prisma generate` after merging.

## 4. Changes to shared, non-RADAR files (review these first)

| File | Change | Why |
|---|---|---|
| `src/app/api/data/index.ts` | Status strings fixed: `"inProcess"` → `"InProgress"`, `"Success"` → `"Succeeded"` (Azure's real values); on a failure, `notifyRadar()` then `sendRadarFailureEmail()`, **once per failure streak** | The old strings never matched, so failures were missed; without the streak check, a pipeline failing every run would notify every run |
| `src/app/layout.tsx` | `<PollingComponent />` enabled | Locally, polling (and so failure detection) only runs while a tab is open |
| `src/app/api/getSSOtoken/route.ts` | Saves the Graph user id as `jinEmployeeId` at login (new and existing users) | `credentialUser`, and so RADAR's membership check, key on it; main only set it in the Azure refresh |
| `src/lib/authMiddleware.ts` | New `requirePermission(request, "resource:action")`: logged in **and** holding the permission directly, via a group, or as admin | Used to gate the routes below |
| `src/app/api/service/route.ts`, `src/app/api/test/route.ts` | Every handler now calls `requirePermission(request, "integration:read")` | They return decrypted secrets and test arbitrary credentials; they were open to any caller |
| `src/app/api/project/route.ts` | `employee_email_id` read from the source's `email_id` column | The old column name returned null |
| `src/config/permissions.ts` | New permission `radar: ["read"]` | Controls the RADAR AI menu entry |
| `src/lib/menu-list.ts`, `src/components/ui/menu.tsx`, `src/components/user-panel/content-layout-user-panel.tsx` | "RADAR AI" menu entry under Watch Tower; the old general chat history panel removed from the sidebar | RADAR replaces the old chat |
| `src/app/home/page.tsx` | Whitespace only | — |
| `src/app/globals.css`, `tailwind.config.ts`, `package.json` | `@tailwindcss/typography` added (chat markdown), RADAR scrollbar and bell-ring styles, npm `allowScripts` for Prisma/bcrypt/esbuild | RADAR UI |
| `.gitignore` | `Caddyfile` ignored | Local reverse proxy config |
| `.env.example` | RADAR variables added (section 2) | — |

## 5. New RADAR-only code

**Pages** (`src/app/radar/`)
- `page.tsx`: the projects page (one card per project the user can see; admins also see an Admin card).
- `[project]/page.tsx`: the history page (the project's name, a new-chat box, the project's chats).
- `[project]/[threadId]/page.tsx`: a chat. It streams replies, shows the tool trace, approval cards and a Stop button, and has a "Show more" for long messages.
- `admin/page.tsx`: the admin dashboard: Home, Projects and Users, with cost, usage, members, notifications and chats.
- `layout.tsx`, `RadarSidebarContext.tsx`: shared header (Back, project name, bell) and the chat sidebar (New Chat, Project memory, History).
- `NotificationBell.tsx`, `greeting.ts`, `types.ts`.

**Components** (`src/components/radar/`)
- `Composer.tsx`: the chat box.
- `ProjectMemoryDialog.tsx`: Memory, SOP and Failure patterns tabs. Memory edits are planned by RADAR, shown as a diff and confirmed before saving.
- `DeleteThreadDialog.tsx`, `RenameThreadDialog.tsx`, `ThreadInfoDialog.tsx`.
- `admin/`: the dashboard views (`HomeView`, `ProjectView`, `UsersView`), shared `ui.tsx` and `types.ts`.

**Library** (`src/lib/radar/`)
- `client.ts`: one function per RADAR endpoint.
- `assertion.ts`, `hmac.ts`, `request-identity.ts`: identity, signing, and the admin gate.
- `notify-failure.ts`, `error-detail/`: failure intake (error detail exists for ADF only).
- `radar-email.ts`: failure emails, and the memory-update email with the full updated memory.
- `memory.ts`: memory kinds and titles.

**API proxies** (`src/app/api/radar/`)
- **Routing and auth:** every route resolves the caller (`resolveRequestIdentity`, or `resolveAdminIdentity` for `admin/*`) and forwards to RADAR. RADAR enforces project membership itself.
- **Routes:**
  - `projects`, `notifications/**`, `threads/**` (including `messages/stream` and `tool-approvals/stream`, both SSE);
  - `messages/[id]/feedback`;
  - `memory/**`, including `memory/plan`, `memory/sop` and `memory/notify` (members only; emails the project's people the updated memory);
  - `admin/overview`, `admin/project`, `admin/users`, `admin/users/[id]`.
- **Removed during RADAR's cleanup:** the non-streamed `threads/[id]/messages` and `threads/[id]/tool-approvals` routes, and `admin/analytics`.

## 6. Merge with main (2026-10-01)

`origin/main` brought in:
- a daily pipeline-failure alert for squad leads (`Alert/`, `scheduler.ts`);
- the scheduler cron fix;
- a backfill admin route;
- the Integrations edit API with new credential schema:
  - `Credential.appProjectId`, linking a credential to its `AppProject`;
  - `User.jinEmployeeId`;
  - a `credentialUser` join table holding each integration's people.

Conflicts and how they were resolved:
- **`.env.example`:** both sets of variables kept.
- **`prisma/schema.prisma`:** `User` keeps `projectAssignments` (ours) and `jinEmployeeId` + `credentials` (main).
- **`src/app/api/service/route.ts`:** main's `PUT` kept as is. It already re-encrypts only secrets that were sent and keeps stored ones, which is the fix `feat-radar` had. It also validates the connection and writes `credentialUser`.
- **Users refresh route and Integrations new and edit pages:** main's code kept (both sides had moved to employee ids).

**Who is on a project (changed with this merge).** RADAR and WatchTower's RADAR code
(`api/radar/projects`, `radar-email.ts`, `memory/notify`) now read project membership from main's
`credentialUser` ↔ `User.jinEmployeeId` (plus manual `UserProjectAssignment` rows).
`Credential.resources` holds people's names and is not used for membership. `feat-radar`'s own
`User.azureObjectId` column (the same id) was removed before it was ever committed.

**After deploying, run main's `/api/admin/backfill` once.** It fills `credentialUser` (and
`appProjectId`) for integrations saved before that table existed; until then, those projects
have no members in RADAR.

## 7. Known security notes (found during this work, not introduced by it)

- `PATCH /api/management/users` (Make/Revoke Admin) has no authentication check.
- Most other `/api/*` routes outside RADAR's are unauthenticated: `src/middleware.ts` protects pages only.

## 8. Testing it

Follow `radar/docs/dev-env.md`:
1. Run both apps.
2. Make yourself admin.
3. Add an ADF project in the Integrations tab with yourself as a resource.
4. Open RADAR AI → the project → start a chat.
5. Trigger a failure (`curl http://localhost:3000/api/data` polls immediately).

`npx tsc --noEmit -p .` should be clean.
