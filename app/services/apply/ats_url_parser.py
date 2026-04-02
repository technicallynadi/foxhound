"""Parse ATS URLs to extract API-specific identifiers.

Each ATS API needs structured tokens parsed from the apply URL:
- Greenhouse: board_token + job_id
- Lever: company + posting_id
- Ashby: company + job_id
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ATSUrlInfo:
    ats_type: str  # "greenhouse" | "lever" | "ashby"
    board_token: str  # company slug / board identifier
    job_id: str  # job or posting ID


# Greenhouse patterns:
#   https://boards.greenhouse.io/{board_token}/jobs/{job_id}
#   https://job-boards.greenhouse.io/{board_token}/jobs/{job_id}
#   https://boards.greenhouse.io/embed/job_app?for={board_token}&token={job_id}
_GH_PATTERNS = [
    re.compile(
        r"(?:boards|job-boards)\.greenhouse\.io/(?P<board>[^/]+)/jobs/(?P<job>\d+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"greenhouse\.io/embed/job_app\?.*for=(?P<board>[^&]+).*token=(?P<job>\d+)",
        re.IGNORECASE,
    ),
]

# Lever patterns:
#   https://jobs.lever.co/{company}/{posting_id}
#   https://jobs.lever.co/{company}/{posting_id}/apply
_LEVER_PATTERN = re.compile(
    r"jobs\.lever\.co/(?P<company>[^/]+)/(?P<posting>[a-f0-9-]+)",
    re.IGNORECASE,
)

# Ashby patterns:
#   https://jobs.ashbyhq.com/{company}/{job_id}
#   https://jobs.ashbyhq.com/{company}/application/{job_id}
_ASHBY_PATTERN = re.compile(
    r"jobs\.ashbyhq\.com/(?P<company>[^/]+)(?:/application)?/(?P<job>[a-f0-9-]+)",
    re.IGNORECASE,
)


def parse_ats_url(url: str) -> ATSUrlInfo | None:
    """Extract ATS API identifiers from a job URL.

    Returns ATSUrlInfo or None if the URL doesn't match any known ATS pattern.
    """
    if not url:
        return None

    # Greenhouse
    for pat in _GH_PATTERNS:
        m = pat.search(url)
        if m:
            return ATSUrlInfo(
                ats_type="greenhouse",
                board_token=m.group("board"),
                job_id=m.group("job"),
            )

    # Lever
    m = _LEVER_PATTERN.search(url)
    if m:
        return ATSUrlInfo(
            ats_type="lever",
            board_token=m.group("company"),
            job_id=m.group("posting"),
        )

    # Ashby
    m = _ASHBY_PATTERN.search(url)
    if m:
        return ATSUrlInfo(
            ats_type="ashby",
            board_token=m.group("company"),
            job_id=m.group("job"),
        )

    return None
