import os
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds
RATE_LIMIT_DELAY = 0.5  # seconds between requests — be polite to public APIs

# Circuit breaker: stop hammering a host that is clearly failing (HTTP 5xx or
# timeouts) so a struggling server (e.g. NI Assembly under a full-history pull)
# can't stall the run at ~96s per timed-out item.
#   - After CIRCUIT_DEGRADE_AT consecutive failures, requests to that host drop
#     to a single attempt with CIRCUIT_FAST_TIMEOUT so failures resolve quickly
#     instead of burning the full retry budget each time.
#   - After CIRCUIT_OPEN_THRESHOLD consecutive failures the circuit "opens":
#     requests to that host fast-fail (return None immediately) for
#     CIRCUIT_COOLDOWN seconds, then one probe is allowed through (half-open) to
#     see if it has recovered — a success closes the circuit and resumes.
# Any open/fast-fail marks the current data type "degraded" so the orchestrator
# saves what it got but records it incomplete, and a later run retries it.
CIRCUIT_DEGRADE_AT = 3        # consecutive failures before fast-timeout mode
CIRCUIT_OPEN_THRESHOLD = 8    # consecutive failures before the circuit opens
CIRCUIT_FAST_TIMEOUT = 10     # seconds per attempt once a host is degrading
CIRCUIT_COOLDOWN = 120        # seconds to fast-fail a downed host before re-probing

# Caps on detail-page fetches for scraped (non-API) sources.
# Listing pages can surface more links than is practical to fetch in one run;
# the scrapers log a warning whenever a cap actually truncates results, so a
# truncated pull is visible in the run log rather than silent.
MAX_QUESTION_DETAIL_PAGES = 5000  # question detail pages per listing (Wales)
MAX_PLENARY_SESSION_PAGES = 300   # plenary session pages per run (Wales)
# Scottish question search pages (10 questions/page). The full archive is ~234k
# questions (~23.4k pages); this covers it. A full pull is slow — narrow --from
# (or rely on resume across same-day runs) if you don't need all of history.
MAX_SCOTTISH_QUESTION_PAGES = 25000

PARLIAMENTS = {
    "ni_assembly": {
        "name": "NI Assembly",
        "enabled": True,
        # Open Data web services — data starts from ~2007
        "api_base": "http://data.niassembly.gov.uk",
    },
    "uk_parliament": {
        "name": "UK Parliament",
        "enabled": True,
        "members_api": "https://members-api.parliament.uk/api",
        # writtenquestions-api.parliament.uk was retired; new domain:
        "questions_api": "https://questions-statements-api.parliament.uk/api",
        "commons_votes_api": "https://commonsvotes-api.parliament.uk/data",
        "lords_votes_api": "https://lordsvotes-api.parliament.uk/data",
        # hansard.parliament.uk/api is the public *website*, not the API — every
        # /api/* path there 404s. The machine-readable Hansard API (spoken debate
        # contributions, written statements, etc.) is served from hansard-api.*.
        "hansard_api": "https://hansard-api.parliament.uk",
    },
    "scottish_parliament": {
        "name": "Scottish Parliament",
        "enabled": True,
        "api_base": "https://data.parliament.scot/api",
    },
    "welsh_parliament": {
        "name": "Welsh Parliament (Senedd)",
        "enabled": True,
        "api_base": "https://senedd.wales",
        # record.assembly.wales redirects here after the Assembly was renamed Senedd
        "record_base": "https://record.senedd.wales",
    },
}
