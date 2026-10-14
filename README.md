# Internship Watcher

A coverage-first internship discovery pipeline that polls official applicant-tracking systems and public career pages, normalizes postings, applies explainable relevance scoring, and emails newly discovered matches.

The project is intentionally built without paid APIs or language-model dependencies. It runs on GitHub Actions and supports Greenhouse, Lever, Workday, Ashby, SmartRecruiters, Workable, USAJOBS, public tracker feeds, and several company-specific sources.

## Highlights

- Polls hundreds of official company boards in parallel.
- Prioritizes source reliability and coverage before ranking.
- Supports software, AI/ML, embedded systems, hardware, robotics, security, technical consulting, and forward-deployed engineering roles.
- Uses explainable fit, season, company, location, and compensation signals.
- Treats compensation and location as ranking signals rather than hard filters.
- Canonicalizes ATS URLs and deduplicates roles across sources.
- Tracks filter-drop reasons so overly aggressive rules remain visible.
- Marks must-cover sources healthy or degraded in the Actions summary.
- Preserves prior reports when a critical source fails.
- Includes offline regression tests for parsers, filtering, ranking, eligibility annotations, and state migration.

## Architecture

```text
Official ATS boards + public trackers
                |
                v
       source-specific fetchers
                |
                v
 normalize -> filter -> deduplicate -> score
                |                    |
                v                    v
       private cached state     email new matches
                |
                v
       generated private reports
```

`watcher.py` contains the fetchers and pipeline. `config.json` contains public source definitions and neutral ranking defaults. Personal preferences are supplied at runtime through an ignored private overlay and are never committed.

## Local setup

```powershell
python -m pip install -r requirements.txt
Copy-Item config.private.example.json config.private.json
python -m unittest -v
python watcher.py
```

Edit `config.private.json` with your preferences. The file and all generated state are ignored by Git.

Email delivery uses these environment variables:

- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `EMAIL_TO`
- Optional: `SMTP_HOST` and `SMTP_PORT`

USAJOBS support additionally uses `USAJOBS_API_KEY` and `USAJOBS_EMAIL`.

## GitHub Actions privacy

The workflow reads a base64-encoded `PRIVATE_CONFIG_B64` repository secret and restores notification state through GitHub Actions cache storage. Personal profiles, previously seen jobs, generated reports, and recipient addresses are therefore not committed to the public repository.

To create the value for `PRIVATE_CONFIG_B64` locally:

```powershell
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((Get-Content config.private.json -Raw)))
```

Add the resulting value as a GitHub Actions repository secret. SMTP and optional USAJOBS values should also be stored as Actions secrets.

## Testing

```powershell
python -m unittest -v
```

The scheduled workflow runs the same suite before every production sweep.

## GitHub internship repositories

The SimplifyJobs/Pitt CSC Summer2027 `dev/README.md` is a required source.
Its HTML tables and older Markdown tables are supported, including continuation
company rows, multiple locations, and application buttons. All categories enter
the existing technical relevance and US-location filters: SWE, AI/ML, hardware,
embedded, robotics, architecture, aerospace, and technical consulting retain the
same preferences. Summer 2027 ranks above Spring 2027; private overlays still apply.
The existing speedyapply and vanshb03 feeds remain complementary sources.
Simplify application links also feed ATS board autodiscovery, alongside direct
company monitoring.

Only application-column link targets are used, preferring employer/ATS links over
Simplify links. Image URLs and company homepages are excluded. Direct ATS records
are processed before repository records. Stable Greenhouse, Lever, Workday, and
Ashby identifiers and tracking-parameter normalization deduplicate application
URLs. Company/title/location signatures suppress duplicate discoveries across
different URLs, both within a sweep and across subsequent sweeps. Those signatures
can merge separate requisitions with identical titles and locations; old state
without signatures gains them as jobs are observed again.

Closed/inactive JSON entries and README application cells marked closed or 🔒 are
excluded. Disappearing listings leave open-role reports after a healthy sweep,
but their notification history remains. Reopening the same role does not alert
again. A repository's closed marker does not override an open official ATS record.
Repository status may lag the employer, and links are not individually checked
for availability. If only a Simplify link exists, it remains a fallback.

Each newly enabled source silently records its first successful sync, even when
other sources already have history. Subsequent unseen matches can alert. Preserve
the Actions state cache to preserve this behavior; clearing state starts a fresh
silent baseline. Baseline email for a completely fresh installation remains opt-in.

Logs show parsed, closed, and actionable row counts. Missing tables, broken
application structures, HTTP errors, and invalid JSON schemas fail visibly and do
not warm the source. Simplify is included in must-cover diagnostics; failure or
an unexpectedly empty result preserves the previous reports while healthy sources
continue tracking and alerting. Inspect the Actions summary and source logs for
failures. Offline tests cover both table formats, link selection, closed entries,
state baselining, duplicate history, and degraded sweeps.

## Design choices

- A dead source should be visible but should not prevent healthy sources from producing results.
- Critical-source failure makes the sweep degraded and prevents authoritative snapshots from being overwritten.
- Missing salary or ambiguous location remains neutral.
- State keys use stable ATS identifiers when possible, avoiding duplicate alerts from locale or URL changes.
- HTML-only sources fail loudly when their expected job-card structure disappears.

## License

MIT
