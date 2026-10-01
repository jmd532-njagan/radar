# Dev environment: from clone to a working RADAR

RADAR has no UI, users or projects of its own. It runs behind **WatchTower** (a separate
Next.js repo), which provides the login, the projects, the platform credentials and the
"RADAR AI" pages, and shares its Postgres database. So you set up WatchTower first, then RADAR,
then connect a project.

## What you need

- **Python 3.12+** and [uv](https://docs.astral.sh/uv/)
- **Node 18+** and npm (WatchTower, and the Prisma CLI that applies RADAR's migrations)
- **PostgreSQL** that both apps can reach
- An **Azure OpenAI** gpt-4o deployment (endpoint, deployment name, key)
- WatchTower's **Entra ID app registration** values, with `http://localhost:3000/callback`
  added as a redirect URI. Microsoft SSO is the only working login.
- About 1 GB free: the first RADAR start downloads the local embedding model
  (`BAAI/bge-base-en-v1.5`, about 440 MB, into the Hugging Face cache).

## 1. WatchTower

```bash
git clone https://github.com/jmangroup/watch-Tower.git
cd watch-Tower
git checkout feat-radar          # the RADAR integration lives on this branch
npm install
cp .env.example .env             # fill in, see below
npx prisma generate
npx prisma migrate deploy
npx prisma db seed               # creates the platform list (adf, fabric, ...) the Integrations tab shows
npm run dev                      # http://localhost:3000
```

In WatchTower's `.env`:
- `DATABASE_URL`
- the Entra SSO values (`NEXT_PUBLIC_AZURE_AUTH_TENANT_ID`, `NEXT_PUBLIC_AZURE_AUTH_CLIENT_ID`,
  `AZURE_AUTH_SECRET_KEY`)
- `NEXT_PUBLIC_BASE_URL=http://localhost:3000`
- `JWT_SECRET_KEY`
- the RADAR block:

```
RADAR_API_BASE_URL=http://localhost:8000
RADAR_WEBHOOK_SECRET=<random, at least 32 chars>
RADAR_ASSERTION_SECRET=<random, at least 32 chars>
```

Generate each secret with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

You also need two groups of values the example file doesn't list; copy them from a teammate's
`.env`:
- `SOURCE_DB_*`: the JIN database the project list is synced from.
- `AZURE_EMAIL_CONNECTION_STRING` and `AZURE_EMAIL_SENDER`: for failure emails. Without them,
  emails fail silently and everything else still works.

## 2. Sign in once and make yourself admin

Open http://localhost:3000 and sign in with Microsoft SSO. That creates your row in
`public."User"`. There's no admin screen for the first admin, so run this against the database:

```sql
UPDATE public."User" SET "isAdmin" = true WHERE email = 'you@jmangroup.com';
```

Sign out and back in. Admins see every WatchTower menu (including **RADAR AI** and
**Integrations**) and, in RADAR, every monitored project read-only plus the admin dashboard
(`/radar/admin`). To *chat* in a project, even an admin must be a project member (step 5).

## 3. RADAR

```bash
git clone https://github.com/jmd532-njagan/radar.git
cd radar
uv sync --all-groups             # Python deps, including dev tools (pytest, ruff, lefthook)
uv run lefthook install          # git hooks: ruff format + lint on commit
npm install                      # the Prisma CLI only; RADAR's code is all Python
cp .env.example .env             # fill in, see below
npx prisma migrate deploy        # creates RADAR's tables in the "radar" schema
uv run python -m uvicorn main:app --reload --app-dir src     # http://localhost:8000
```

Or use Docker: `docker compose up --build` (still needs `.env` and the migration step).

RADAR's `.env` (every value is required; see `.env.example`):

| Variable | Value |
|---|---|
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_KEY` | Your Azure OpenAI deployment |
| `DATABASE_URL` | WatchTower's database, as `postgresql+asyncpg://…` |
| `RADAR_SCHEMA_DATABASE_URL` | The same database as `postgresql://…?schema=radar` (Prisma only) |
| `HMAC_SECRET` | = WatchTower `RADAR_WEBHOOK_SECRET` |
| `RADAR_ASSERTION_SECRET` | = WatchTower `RADAR_ASSERTION_SECRET` |
| `WATCHTOWER_CREDENTIAL_KEY` | = WatchTower `JWT_SECRET_KEY` (decrypts the platform credentials) |

The three shared values must match exactly, or RADAR rejects WatchTower's calls.

Check it's up: `curl http://localhost:8000/health` returns `{"status":"ok"}`. The first start
takes about a minute while the embedding model downloads and loads.

## 4. Load the projects

WatchTower's project list is synced from the JIN database. Open
http://localhost:3000/projects (the page isn't in the menu) and click the refresh icon next to
**All Projects**. Opening the page also triggers the sync. Until this runs, the project picker
in the next step is empty.

## 5. Connect a project (Integrations tab)

1. **Integrations** → the **ADF** card → **+ Add New App Registration**.
2. Fill in the form:
   - **Project Name:** type and pick it from the list; it must be one of the synced projects.
   - **Tenant ID**, **Client ID (Application ID)**, **Client Secret**, **Subscription ID**,
     **Resource Group Name**, **Data Factory Name:** the service principal and factory.
3. **Test Connection.** On success it loads the factory's pipelines and the project's people.
4. **Pipelines:** choose the ones to monitor. Only these are polled and sent to RADAR.
5. **Resource Selection:** choose the people who work on the project, **including yourself**.
6. **Save Configuration.**

That writes one `public."Credential"` row, which is everything RADAR needs; there's nothing to
add on the RADAR side. The project now appears under **RADAR AI** for:
- the resources you picked (matched to their WatchTower account by Azure AD object id, so each
  must have signed in to WatchTower at least once);
- admins, read-only.

To add someone who isn't a resource, run this SQL:

```sql
INSERT INTO public."UserProjectAssignment" (id, "userId", "projectName", "notifyOnFailure")
SELECT gen_random_uuid(), id, '<exact project name>', true
FROM public."User" WHERE email = 'someone@jmangroup.com';
```

Members get the failure emails; set `notifyOnFailure = false` to opt one out.

## 6. Try it

- **Chat:** RADAR AI → pick the project → start a chat ("list the pipelines", "why did X fail
  last night?").
- **Failures:** WatchTower polls ADF every 10 minutes while a browser tab is open (in
  production a scheduler process does it). To poll right away, open
  `curl http://localhost:3000/api/data`. A failed run of a monitored pipeline then shows up in
  RADAR AI's notifications, with a seed message and a chat.
- **SOP:** RADAR AI → the project's Memory panel → SOP → upload the project's `.docx` SOP. It's
  chunked, searched during chats, and its known issues come back as proposed failure patterns
  for you to approve.

## Troubleshooting

| Symptom | Cause |
|---|---|
| RADAR won't start: "Field required" / "must be set to a real value" | A value missing from RADAR's `.env` |
| RADAR AI shows no projects | You're not a resource or assigned (step 5), or the project's `Credential` was deleted |
| 401 on every RADAR call | `RADAR_ASSERTION_SECRET` differs between the two `.env` files |
| Failures never reach RADAR (401 in RADAR's log) | `HMAC_SECRET` ≠ WatchTower `RADAR_WEBHOOK_SECRET` |
| "Failed to decrypt client_secret" | `WATCHTOWER_CREDENTIAL_KEY` ≠ WatchTower `JWT_SECRET_KEY` |
| "has no ADF integration in WatchTower" | The project has no live ADF `Credential` row (step 5) |
| No failure emails | `AZURE_EMAIL_*` missing in WatchTower's `.env` |

## Logs

Set up in `main.py`. Every line is timestamped, and RADAR's own loggers write at `LOG_LEVEL`
(`config/settings.py`: `"INFO"`, or `"DEBUG"` to chase a problem). Libraries (httpx, openai,
azure, sentence-transformers) only log warnings. Uvicorn's access log drops successful GETs
(WatchTower's polling, `/health`), so what shows is writes, 4xx/5xx and RADAR's own events.

RADAR writes one `key=value` line per event:
- a failure received (with its pattern and how it matched) or rejected;
- a turn done (tools, tokens), paused for approval, or stopped;
- an approval granted, denied or expired;
- an RBAC denial;
- a guardrail block (the score is logged on every message at DEBUG);
- an SOP processed.

To follow one failure through the logs, search for its `investigation=` or `thread=` value.

## Tests and linting

```bash
uv run pytest                  # tests/ mirrors src/; SQLite in memory, no real credentials
uv run ruff check --fix .      # lint
uv run ruff format .           # format
```

lefthook runs ruff on every commit and the full check before a push. Working on RADAR with an AI
assistant? Point it at `docs/claude.md` first.
