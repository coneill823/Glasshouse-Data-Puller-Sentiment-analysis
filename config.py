import os
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds
RATE_LIMIT_DELAY = 0.5  # seconds between requests — be polite to public APIs

# Caps on detail-page fetches for scraped (non-API) sources.
# Listing pages can surface more links than is practical to fetch in one run;
# the scrapers log a warning whenever a cap actually truncates results, so a
# truncated pull is visible in the run log rather than silent.
MAX_QUESTION_DETAIL_PAGES = 1000  # question detail pages per listing (Scotland / Wales)
MAX_PLENARY_SESSION_PAGES = 300   # plenary session pages per run (Wales)

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
