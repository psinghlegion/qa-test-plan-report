#!/usr/bin/env python3
"""Fetch PR data from legionco/qa-test-plan and generate data.json for the dashboard."""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone

REPO = "legionco/qa-test-plan"

AUTHOR_MAP = {
    "psinghlegion": "Priya Singh",
    "GunjanAnand-Legion": "Gunjan Anand",
    "mmao-legion": "Mary Mao",
    "vthorat-legion": "Vikas Thorat",
    "pbhatia-legion": "Prateek Bhatia",
    "SZhang-Legion": "Stoneman Zhang",
    "ewang-legion": "Eric Wang",
    "Fiona168": "Fiona Feng",
    "jbanzah": "Jeff Banzah",
    "vsrivastava-legion": "Vikas Srivastava",
    "skumark-legion": "Santhosh Kumar K",
}

TICKET_PREFIX_TO_TEAM = {
    "SCH": "SCH",
    "ELM": "ELM",
    "TA": "TA",
    "PLT": "PLT-Core",
    "GENAI": "GENAI",
    "LP": "LP",
    "OPS": "OPS",
}


def parse_body(body):
    """Extract metadata from PR body text."""
    meta = {}

    # Skill / type
    m = re.search(r"\*\*Type:\*\*\s*(feature|backlog|delta|regression)", body, re.I)
    if m:
        meta["skill"] = m.group(1).lower()

    # Team
    m = re.search(r"\*\*Team:\*\*\s*([A-Za-z][\w-]*)", body)
    if m:
        meta["team"] = m.group(1).strip()

    # Module — try multiple patterns
    m = re.search(
        r"\*\*(?:Ticket\s*/\s*Module|Ticket / Module):\*\*\s*(.+?)(?:\n|·|$)", body
    )
    if m:
        val = m.group(1).strip()
        val = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", val)  # strip markdown links
        # If it's just a ticket number like "SCH-22841", skip it as module
        if not re.match(r"^[A-Z]+-\d+$", val.strip()):
            # Strip leading ticket number + separator
            val = re.sub(r"^[A-Z]+-\d+\s*[-—–]\s*", "", val).strip()
            if val:
                meta["module"] = val
    if "module" not in meta:
        m = re.search(r"\*\*Module:\*\*\s*(.+?)(?:\n|·|$)", body)
        if m:
            meta["module"] = m.group(1).strip()

    # Scenario count — multiple formats
    m = re.search(r"\*\*Scenario[s]?\s*count:\*\*\s*(\d+)", body, re.I)
    if not m:
        m = re.search(r"\*\*Scenarios:\*\*\s*(\d+)", body, re.I)
    if not m:
        m = re.search(r"(\d+)\s+(?:tagged\s+)?(?:BDD/)?(?:Gherkin\s+)?scenarios", body, re.I)
    if m:
        meta["scenarios"] = int(m.group(1))

    # Confluence page
    m = re.search(
        r"\*\*(?:Confluence\s*page|Source of record):\*\*\s*(https://legiontech\.atlassian\.net/wiki/\S+)",
        body,
    )
    if not m:
        m = re.search(
            r"(?:Reviewed in Confluence|Confluence[:\s]+)\s*(https://legiontech\.atlassian\.net/wiki/\S+)",
            body,
        )
    if not m:
        # Bare URL in body
        m = re.search(r"(https://legiontech\.atlassian\.net/wiki/spaces/TEST/pages/\d+\S*)", body)
    if m:
        meta["confluence"] = m.group(1).strip().rstrip(")")
    else:
        # Bare page ID: "Confluence page 4880629795"
        m = re.search(r"Confluence\s+page\s+(\d{10,})", body, re.I)
        if m:
            meta["confluence"] = "https://legiontech.atlassian.net/wiki/spaces/TEST/pages/" + m.group(1)

    return meta


def module_from_title(title):
    """Extract module name from PR title as fallback."""
    # "QA Plan: TA-22752 — Paid Incomplete Shift Gaps"
    m = re.search(r"QA\s+Plan:\s*[A-Z]+-\d+\s*[-—–]\s*(.+)", title)
    if m:
        return m.group(1).strip()
    # "Backlog Manifest: Roster"
    m = re.search(r"(?:Backlog\s+)?Manifest:\s*(?:[A-Z]+\s*/\s*)?(.+)", title)
    if m:
        return m.group(1).strip()
    # "QA Plan: SCH-23314 – Delete Scheduled Shifts..."
    m = re.search(r"[-—–]\s*(.+)", title)
    if m:
        return m.group(1).strip()
    return title


def team_from_title(title):
    """Try to infer team from ticket prefix in title."""
    m = re.search(r"(?:^|[\s:])([A-Z]+)-\d+", title)
    if m:
        prefix = m.group(1)
        return TICKET_PREFIX_TO_TEAM.get(prefix, prefix)
    # "Backlog Manifest: SCH / Flex Group" pattern
    m = re.search(r"(?:Manifest|Plan):\s*([A-Z]+(?:-[A-Za-z]+)?)\s*/", title)
    if m:
        return m.group(1)
    return ""


def skill_from_title(title):
    """Infer skill type from PR title."""
    t = title.lower()
    if "backlog" in t or "manifest" in t:
        return "backlog"
    if "regression" in t:
        return "regression"
    if "delta" in t:
        return "delta"
    return "feature"


def format_date(iso_str):
    """Convert ISO date string to readable format."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y")
    except Exception:
        return iso_str[:10]


def find_confluence_in_diff(pr_number):
    """Fetch PR diff and look for Confluence references in file content."""
    cmd = ["gh", "pr", "diff", str(pr_number), "--repo", REPO]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    diff = result.stdout
    # Full URL
    m = re.search(r"(https://legiontech\.atlassian\.net/wiki/spaces/TEST/pages/\d+)", diff)
    if m:
        return m.group(1)
    # Bare page ID
    m = re.search(r"Confluence\s+page\s+(\d{10,})", diff, re.I)
    if m:
        return "https://legiontech.atlassian.net/wiki/spaces/TEST/pages/" + m.group(1)
    return ""


def main():
    cmd = [
        "gh", "pr", "list",
        "--repo", REPO,
        "--state", "all",
        "--limit", "200",
        "--json", "number,title,state,author,createdAt,updatedAt,mergedAt,body,url",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error fetching PRs: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    prs = json.loads(result.stdout)

    # Keep only OPEN and MERGED (exclude CLOSED)
    prs = [pr for pr in prs if pr["state"] in ("OPEN", "MERGED")]

    data = []
    for pr in prs:
        body = pr.get("body") or ""
        meta = parse_body(body)

        # If no Confluence link found in body, scan the PR diff
        if not meta.get("confluence"):
            confluence = find_confluence_in_diff(pr["number"])
            if confluence:
                meta["confluence"] = confluence

        # Author
        login = pr["author"]["login"]
        author_name = pr["author"].get("name") or ""
        if not author_name:
            author_name = AUTHOR_MAP.get(login, login)

        # Skill
        skill = meta.get("skill") or skill_from_title(pr["title"])

        # Team
        team = meta.get("team") or team_from_title(pr["title"])
        # Normalize PLT variants
        if team == "PLT":
            team = "PLT-Core"

        # Module
        module = meta.get("module") or module_from_title(pr["title"])

        # Date
        date_str = pr.get("mergedAt") or pr.get("updatedAt") or pr.get("createdAt", "")

        entry = {
            "id": pr["number"],
            "title": pr["title"],
            "skill": skill,
            "team": team,
            "module": module,
            "owner": author_name,
            "scenarios": meta.get("scenarios", 0),
            "status": "Merged" if pr["state"] == "MERGED" else "Open",
            "lastModified": format_date(date_str),
            "confluence": meta.get("confluence", ""),
            "url": pr["url"],
        }
        data.append(entry)

    # Sort by PR number descending (newest first)
    data.sort(key=lambda x: x["id"], reverse=True)

    output = {
        "generated": datetime.now().strftime("%b %d, %Y %I:%M %p"),
        "repo": REPO,
        "count": len(data),
        "data": data,
    }

    output_path = sys.argv[1] if len(sys.argv) > 1 else "data.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(data)} PRs to {output_path}")


if __name__ == "__main__":
    main()
