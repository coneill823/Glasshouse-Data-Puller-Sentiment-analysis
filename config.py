import os
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds
RATE_LIMIT_DELAY = 0.5  # seconds between requests — be polite to public APIs

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
        "hansard_api": "https://hansard.parliament.uk/api",
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
        "record_base": "https://record.assembly.wales",
    },
}
