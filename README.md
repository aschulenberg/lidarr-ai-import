# lidarr-ai-import

A companion service for [Lidarr](https://lidarr.audio/) that uses an LLM to resolve
imports Lidarr's own matcher gave up on - especially the case where a song was
released more than once (a standalone **Single**, an **EP**, and later a full
**Album**) and Lidarr can't tell which one a downloaded file actually belongs to.

It also scans your "missing" list and flags tracks that aren't really missing -
you already have the same recording, just filed under a different release.

## Why this isn't a "real" Lidarr plugin

Lidarr does have a plugin system (the `plugins` branch), but it only extends
**indexers**, **download clients**, and **notification connections** - it has no
extension point inside the core import/matching engine, which is exactly the part
that needs to change here. So this runs as a separate process that talks to Lidarr
over its REST API instead: it reads `/api/v1/manualimport` and `/api/v1/wanted/missing`,
asks an AI model to disambiguate, and (optionally) submits the result back via
the same Manual Import API the Lidarr UI itself uses. No Lidarr branch switch
required, nothing installed into Lidarr itself.

## The two workflows

**`resolve`** - polls Lidarr for anything sitting in Manual Import limbo. For each
file, it pulls every album/release/track for that artist (not just the one Lidarr
guessed), finds tracks with a similar title, and hands the AI a side-by-side
comparison: which Single/EP/Album release does this specific file belong to, based
on title wording and track duration. If confident, it submits the match back to
Lidarr exactly like you'd do by hand in the Manual Import screen.

**`reconcile`** - walks your wanted/missing list and checks whether the artist's
library already contains a near-identical title that just lives under a different
release. The AI confirms whether it's really the same recording (filed differently)
or a genuinely distinct version (radio edit, live, remix) that's still a real gap.
This is report-only - it tells you what's actually going on, it does not move or
delete files. Re-filing an already-imported file under a different track is a
manual step in Lidarr's own UI for now (see Limitations).

Every decision - applied, skipped, or flagged for review - is written to a local
SQLite log (`DB_PATH`) so you can audit what happened and why.

## Setup

1. **Lidarr API key**: Settings → General → Security → API Key.
2. Copy `.env.example` to `.env` and fill in `LIDARR_URL` / `LIDARR_API_KEY`.
3. Pick an AI provider in `.env`:
   - `AI_PROVIDER=anthropic` (default) - set `AI_API_KEY` to an Anthropic API key.
   - `AI_PROVIDER=openai` - set `AI_API_KEY` to an OpenAI key.
   - `AI_PROVIDER=ollama` - point `AI_BASE_URL` at your local Ollama (default
     `http://localhost:11434`), no API key needed.
4. Leave `DRY_RUN=true` for your first runs - every decision is logged but nothing
   is sent to Lidarr.
5. Run it:

   ```bash
   pip install -r requirements.txt
   python main.py resolve            # one-shot
   python main.py reconcile          # one-shot, prints a report
   python main.py reconcile --json report.json
   python main.py serve              # both workflows, continuously
   ```

   Or with Docker - see `docker-compose.example.yml`. **It needs to see the same
   file paths Lidarr does**, so mount the same music/downloads volumes.

6. Review `data/lidarr_ai_import.db` (or the log output) for a while. When you're
   happy with the decisions it's making, set `DRY_RUN=false`.

## Safety notes

- Dry-run by default. Nothing touches your library until you turn it off.
- `CONFIDENCE_THRESHOLD` (default `0.85`) - anything below this is left as
  `needs_review` and never auto-applied, regardless of dry-run.
- The resolver will never auto-replace a track slot that already has a file -
  that always gets downgraded to `needs_review` for a human to look at.
- The reconciler never mutates anything; it only reports.
- `REPROCESS_COOLDOWN_MINUTES` (default 720) keeps it from re-asking the AI about
  the same unresolved file or missing track on every single poll.

## Limitations

- The resolver only widens its search across an artist's discography once Lidarr
  has at least identified the *artist* for a file. If Lidarr can't determine the
  artist at all, the file is flagged `needs_review` rather than guessed at.
- The reconciler is intentionally report-only. Moving an already-imported file to
  satisfy a different "missing" slot would mean re-associating a library file with
  a different track/release, and there isn't a Manual-Import-style API for that -
  doing it via undocumented endpoints felt like the wrong kind of risk to take
  unattended on someone's real media library. For now, use the report to go fix
  those by hand in Lidarr's Manual Import screen.
- Manual-import payload field names are round-tripped from whatever Lidarr's own
  `GET /api/v1/manualimport` returns rather than hardcoded, specifically to survive
  small API differences between Lidarr versions. Track duration is assumed to be
  in milliseconds (Lidarr's convention) - if your version differs, the duration
  signal shown to the AI will be off, but it's a soft signal, not a correctness
  requirement (the AI just falls back to title evidence / needs_review more often).
