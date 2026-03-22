"""
Run this locally to see what text the scraper actually extracts from a remedy page.
This helps us fix the section-parsing regex.

Usage:
    python debug_scraper.py
"""

import re
import requests
from bs4 import BeautifulSoup

# ── same patterns as scraper.py ──────────────────────────────────────────────
_STOP_RE = re.compile(
    r'is available at Remedia|Other names for this|'
    r'This is a chapter|powered by|'
    r'Copyright\s*©|Imprint',
    re.IGNORECASE,
)
_SKIP_RE = re.compile(
    r'more information and order|'
    r'Free Materia Medica books|'
    r'Materia Medica by William Boericke|'
    r'5,500 homeopathic|66,000 customers|'
    r'Manual potenti|rating of the product|excellent',
    re.IGNORECASE,
)

HEADERS = {"User-Agent": "Mozilla/5.0 (research bot; homeopathy scraper)"}


def get_page_text(soup: BeautifulSoup, remedy_name: str) -> str:
    full = soup.get_text(separator="\n")
    pos = full.upper().find(remedy_name.upper())
    if pos != -1:
        full = full[pos + len(remedy_name):]
    lines = []
    for line in full.splitlines():
        s = line.strip()
        if s and _STOP_RE.search(s):
            break
        if s and _SKIP_RE.search(s):
            continue
        lines.append(s)
    return "\n".join(lines)


def debug_page(url: str, remedy_name: str):
    print(f"\n{'='*60}")
    print(f"URL:    {url}")
    print(f"Name:   {remedy_name}")
    print('='*60)

    resp = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")
    text = get_page_text(soup, remedy_name)

    print(f"\n--- First 1500 characters of extracted text ---\n")
    print(text[:1500])
    print(f"\n--- Total length: {len(text)} chars ---")

    print(f"\n--- All non-empty lines (first 60) ---\n")
    lines = [l for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines[:60]):
        print(f"  {i+1:3d}  {repr(line)}")


if __name__ == "__main__":
    # Test with two well-known remedies
    debug_page(
        "https://www.materiamedica.info/en/materia-medica/william-boericke/belladonna",
        "BELLADONNA",
    )
    debug_page(
        "https://www.materiamedica.info/en/materia-medica/william-boericke/arsenicum-album",
        "ARSENICUM ALBUM",
    )
