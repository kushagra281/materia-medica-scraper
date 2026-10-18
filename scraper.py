"""
Homeopathic Materia Medica Scraper
====================================
Sources : materiamedica.info  |  homeoint.org
Book    : William Boericke — Pocket Manual of Homoeopathic Materia Medica (1901)
DB      : PostgreSQL  (see schema.sql)

Install:
    pip install requests beautifulsoup4 psycopg2-binary

Run:
    python scraper.py
"""

import os
import re
import sys
import time
import logging
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import psycopg2
import psycopg2.extras

import config


# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════

_handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
if config.LOG_FILE:
    _handlers.append(logging.FileHandler(config.LOG_FILE, encoding="utf-8"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=_handlers,
)
log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class Section:
    heading: str      # Exact heading from the book, e.g. "Mind"
    order: int        # 1-based position in document
    content: str      # Full text under that heading


@dataclass
class Remedy:
    slug:         str
    name:         str
    common_name:  str
    introduction: str
    sections:     list[Section] = field(default_factory=list)
    source_site:  str = ""
    source_url:   str = ""


# ═══════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════

def db_connect():
    try:
        conn = psycopg2.connect(**config.DB)
        conn.autocommit = False
        log.info("Connected to PostgreSQL '%s'.", config.DB["dbname"])
        return conn
    except psycopg2.OperationalError as exc:
        log.critical("PostgreSQL connection failed: %s", exc)
        sys.exit(1)


# FORCE_REFRESH=1 re-scrapes pages that are already in the database (needed once to repair
# the common_name / introduction / missing-section problems of earlier runs).
FORCE_REFRESH = os.environ.get("FORCE_REFRESH", "") == "1"


def url_already_scraped(conn, url: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM remedies WHERE source_url = %s", (url,))
        return cur.fetchone() is not None


def save_remedy(conn, remedy: Remedy) -> None:
    total_chars = (
        len(remedy.name) + len(remedy.common_name)
        + len(remedy.introduction)
        + sum(len(s.content) for s in remedy.sections)
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO remedies
                (slug, name, common_name, introduction,
                 source_site, source_url,
                 section_count, total_chars)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_url) DO UPDATE SET
                name         = EXCLUDED.name,
                common_name  = EXCLUDED.common_name,
                introduction = EXCLUDED.introduction,
                section_count= EXCLUDED.section_count,
                total_chars  = EXCLUDED.total_chars,
                scraped_at   = NOW()
            RETURNING id
            """,
            (
                remedy.slug, remedy.name, remedy.common_name,
                remedy.introduction, remedy.source_site, remedy.source_url,
                len(remedy.sections), total_chars,
            ),
        )
        remedy_id = cur.fetchone()[0]
        cur.execute("DELETE FROM remedy_sections WHERE remedy_id = %s", (remedy_id,))
        if remedy.sections:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO remedy_sections
                    (remedy_id, heading, heading_order, content, char_count)
                VALUES %s
                """,
                [
                    (remedy_id, s.heading, s.order, s.content, len(s.content))
                    for s in remedy.sections
                ],
            )
    conn.commit()


def log_scrape(conn, url: str, status: str, issues: list[str] = None) -> None:
    message = " | ".join(issues) if issues else ""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scrape_log (url, status, message) VALUES (%s, %s, %s)",
            (url, status, message),
        )
    conn.commit()


# ═══════════════════════════════════════════════════════════════
# HTTP
# ═══════════════════════════════════════════════════════════════

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (compatible; MateriaMedicaResearchBot/1.0; "
        "non-commercial educational scraper)"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
})


def fetch(url: str) -> Optional[BeautifulSoup]:
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            resp = _SESSION.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as exc:
            log.warning("  [%d/%d] fetch error: %s — %s",
                        attempt, config.MAX_RETRIES, url, exc)
            if attempt < config.MAX_RETRIES:
                time.sleep(2 ** attempt)
    return None


# ═══════════════════════════════════════════════════════════════
# SECTION PARSER
# ═══════════════════════════════════════════════════════════════

# Boericke's format: "HeadingWord.--  content text..."
# Confirmed on Arsenicum Album, Belladonna, Nux Vomica pages
_SECTION_RE = re.compile(
    r'^([A-Z][A-Za-z]*(?:[\s\-/][A-Za-z]+){0,5})\.--\s*(.*)'
)

# Hard stop — stop reading when we hit true footer lines (never appear before content)
_STOP_RE = re.compile(
    r'is available at Remedia|Other names for this|'
    r'This is a chapter|powered by|'
    r'Copyright\s*©|Imprint',
    re.IGNORECASE,
)

# Skip-only — discard line but keep reading (appear in nav before content)
_SKIP_RE = re.compile(
    r'more information and order|'
    r'Free Materia Medica books|'
    r'Materia Medica by William Boericke|'
    r'5,500 homeopathic|66,000 customers|'
    r'Manual potenti|rating of the product|excellent',
    re.IGNORECASE,
)

_FOOTER_RE = _STOP_RE  # backward compat


def _clean(text: str) -> str:
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'\s+([,.;:!?)])', r'\1', text)      # "word ," -> "word,"
    return re.sub(r'\(\s+', '(', text)


def get_page_text(soup: BeautifulSoup, remedy_name: str) -> str:
    """
    Extract remedy content from the full page text.

    Gets the entire page as text, finds the remedy name,
    takes everything after it, and strips footer noise.

    This approach works regardless of HTML nesting depth.
    """
    full = soup.get_text(separator="\n")

    # Find remedy name and take content after it
    pos = full.upper().find(remedy_name.upper())
    if pos != -1:
        full = full[pos + len(remedy_name):]

    lines = []
    for line in full.splitlines():
        s = line.strip()
        # Hard stop at true footer markers
        if s and _STOP_RE.search(s):
            break
        # Skip navigation noise but keep reading
        if s and _SKIP_RE.search(s):
            continue
        lines.append(s)

    return "\n".join(lines)


def get_text_after_h1(soup: BeautifulSoup) -> str:
    """
    Remedy text that follows the page's <h1>.

    The old get_page_text() searched the whole page for the remedy name and took everything
    after the FIRST hit - which is the <title> / navigation - so every remedy got the site
    navigation ("Index A B C ... Z 123") in its introduction and "Materia Medica" (a
    breadcrumb) as its common name. Starting at the <h1> avoids that.
    """
    h1 = soup.find("h1")
    if h1 is None:
        return ""
    lines: list[str] = []
    for node in h1.find_all_next(string=True):
        if node.parent is not None and node.parent.name in ("script", "style", "noscript"):
            continue
        if node.find_parent("h1") is not None:      # the title itself is not part of the text
            continue
        s = str(node).strip()
        if s and _STOP_RE.search(s):
            break
        if s and _SKIP_RE.search(s):
            continue
        lines.append(s)
    return "\n".join(lines)


def parse_sections(body_text: str) -> tuple[str, list[Section]]:
    """
    Split body text into introduction + sections.
    Lines matching "Heading.--  text" start a new section.
    All preceding lines are the introduction.
    """
    intro_lines: list[str] = []
    sections:    list[Section] = []
    cur_heading: Optional[str] = None
    cur_lines:   list[str] = []
    order:       int = 0
    in_intro:    bool = True

    def flush():
        nonlocal cur_heading, cur_lines
        if cur_heading is None:
            return
        content = _clean(" ".join(l for l in cur_lines if l))
        if content:
            sections.append(Section(heading=cur_heading, order=order, content=content))
        cur_heading = None
        cur_lines = []

    for raw_line in body_text.splitlines():
        line = raw_line.strip()

        if not line:
            (cur_lines if not in_intro else intro_lines).append("")
            continue

        m = _SECTION_RE.match(line)
        if m:
            if in_intro:
                while intro_lines and not intro_lines[-1]:
                    intro_lines.pop()
            else:
                flush()
            in_intro = False
            order += 1
            raw_heading = m.group(1).strip()
            existing_headings = [s.heading for s in sections]
            if raw_heading in existing_headings:
                count = sum(1 for h in existing_headings if h == raw_heading or h.startswith(raw_heading + ' '))
                cur_heading = f"{raw_heading} {count + 1}"
            else:
                cur_heading = raw_heading
            first = m.group(2).strip()
            cur_lines = [first] if first else []
        else:
            (cur_lines if not in_intro else intro_lines).append(line)

    flush()
    introduction = _clean(" ".join(l for l in intro_lines if l))
    return introduction, sections


# ═══════════════════════════════════════════════════════════════
# QUALITY GATE
# ═══════════════════════════════════════════════════════════════

def quality_check(remedy: Remedy) -> list[str]:
    issues: list[str] = []

    if not remedy.name:
        issues.append("MISSING: name is empty")
    if not remedy.common_name:
        issues.append("MISSING: common_name is empty")
    if not remedy.introduction:
        issues.append("MISSING: introduction is empty")
    elif len(remedy.introduction) < config.MIN_INTRODUCTION_CHARS:
        issues.append(
            f"THIN: introduction {len(remedy.introduction)} chars "
            f"(min {config.MIN_INTRODUCTION_CHARS})"
        )
    if not remedy.sections:
        issues.append("MISSING: no sections extracted")
    elif len(remedy.sections) < config.MIN_SECTIONS_COUNT:
        issues.append(
            f"THIN: only {len(remedy.sections)} sections "
            f"(min {config.MIN_SECTIONS_COUNT})"
        )
    for s in remedy.sections:
        if not s.content:
            issues.append(f"EMPTY section: '{s.heading}'")
        elif len(s.content) < config.MIN_SECTION_CHARS:
            issues.append(
                f"THIN section: '{s.heading}' {len(s.content)} chars "
                f"(min {config.MIN_SECTION_CHARS})"
            )
    total = (
        len(remedy.name) + len(remedy.common_name)
        + len(remedy.introduction)
        + sum(len(s.content) for s in remedy.sections)
    )
    if total < config.MIN_TOTAL_CHARS:
        issues.append(f"TOTAL TOO SMALL: {total} chars (min {config.MIN_TOTAL_CHARS})")

    return issues


# ═══════════════════════════════════════════════════════════════
# SOURCE 1 — materiamedica.info
# ═══════════════════════════════════════════════════════════════

def mm_collect_urls() -> list[str]:
    log.info("Collecting URLs from materiamedica.info …")
    soup = fetch(config.MATERIAMEDICA_INDEX)
    if soup is None:
        log.error("Cannot load index. Skipping.")
        return []
    urls: list[str] = []
    for a in soup.select("a[href]"):
        href = a["href"].strip()
        if re.match(
            r'^/en/materia-medica/william-boericke/[a-z0-9][a-z0-9\-]+$', href
        ):
            full = config.MATERIAMEDICA_BASE + href
            if full not in urls:
                urls.append(full)
    log.info("  → %d URLs found.", len(urls))
    return urls


def mm_parse(url: str, soup: BeautifulSoup) -> Optional[Remedy]:
    """
    Parse one materiamedica.info remedy page.

    Uses full page text extraction — does not rely on HTML siblings.
    Page structure confirmed on Arsenicum Album, Belladonna, Nux Vomica:
      <h1> REMEDY NAME </h1>
      Common name on first line
      Introduction paragraphs
      Mind.-- ...
      Head.-- ...
      ...
      <h4> footer </h4>
    """
    slug = url.rstrip("/").split("/")[-1]

    # Get remedy name from <h1>
    h1 = soup.find("h1")
    if h1 is None:
        log.warning("  No <h1> on %s", url)
        return None
    name = _clean(h1.get_text())
    if not name:
        return None

    # Text that follows the <h1> (see get_text_after_h1)
    body_text = get_text_after_h1(soup)

    # First non-blank, non-section line = common name
    common_name = ""
    body_lines = body_text.splitlines()
    start_idx = 0
    for i, line in enumerate(body_lines):
        s = line.strip()
        if not s:
            continue
        if not _SECTION_RE.match(s):
            common_name = _clean(s).rstrip('.')
            start_idx = i + 1
        break

    body_text = "\n".join(body_lines[start_idx:])

    # Parse introduction + sections
    introduction, sections = parse_sections(body_text)

    return Remedy(
        slug=slug,
        name=name,
        common_name=common_name,
        introduction=introduction,
        sections=sections,
        source_site="materiamedica.info",
        source_url=url,
    )


# ═══════════════════════════════════════════════════════════════
# SOURCE 2 — homeoint.org
# ═══════════════════════════════════════════════════════════════

def hi_collect_urls() -> list[str]:
    log.info("Collecting URLs from homeoint.org …")
    all_urls: list[str] = []
    for letter in config.HOMEOINT_LETTERS:
        page_url = config.HOMEOINT_BASE + f"{letter}.htm"
        soup = fetch(page_url)
        time.sleep(config.REQUEST_DELAY_SECONDS)
        if soup is None:
            log.warning("  Cannot load '%s' — skipping.", letter)
            continue
        found = 0
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if re.match(rf'^{re.escape(letter)}/\w+\.htm$', href, re.IGNORECASE):
                full = urljoin(config.HOMEOINT_BASE, href)
                if full not in all_urls:
                    all_urls.append(full)
                    found += 1
        log.info("  Letter '%s': %d links.", letter, found)
    log.info("  → %d total homeoint.org URLs.", len(all_urls))
    return all_urls


def hi_parse(url: str, soup: BeautifulSoup) -> Optional[Remedy]:
    slug = url.rstrip("/").split("/")[-1].replace(".htm", "")

    name = ""
    for tag in ("h1", "h2", "h3"):
        el = soup.find(tag)
        if el:
            candidate = _clean(el.get_text())
            if candidate and len(candidate) < 120 and not candidate.startswith("H.I."):
                name = candidate
                break
    if not name:
        b = soup.find("b")
        if b:
            name = _clean(b.get_text())
    if not name:
        name = slug.replace("-", " ").upper()

    body_text = get_page_text(soup, name)

    # homeoint-specific footer — stop before these
    clean_lines = []
    for line in body_text.splitlines():
        if re.search(
            r'M[eé]di-T|Click HERE|Buy a copy|Norwegian|Norv[eé]gian|'
            r'Presented by|H\.I\. English|Remerciements',
            line, re.IGNORECASE
        ):
            break
        clean_lines.append(line)
    body_text = "\n".join(clean_lines)

    # Common name
    common_name = ""
    body_lines = body_text.splitlines()
    start_idx = 0
    for i, line in enumerate(body_lines):
        s = line.strip()
        if not s:
            continue
        if s.upper() != name.upper() and not _SECTION_RE.match(s) and len(s) < 120:
            common_name = _clean(s)
            start_idx = i + 1
        break

    body_text = "\n".join(body_lines[start_idx:])
    introduction, sections = parse_sections(body_text)

    return Remedy(
        slug=slug,
        name=name,
        common_name=common_name,
        introduction=introduction,
        sections=sections,
        source_site="homeoint.org",
        source_url=url,
    )


# ═══════════════════════════════════════════════════════════════
# SCRAPE RUNNER
# ═══════════════════════════════════════════════════════════════

def run(conn, urls: list[str], parser_fn, label: str):
    total   = len(urls)
    success = skipped = errors = 0

    log.info("=" * 65)
    log.info("START  %s  (%d URLs)", label, total)
    log.info("=" * 65)

    for i, url in enumerate(urls, start=1):
        log.info("[%d/%d]  %s", i, total, url)

        if not FORCE_REFRESH and url_already_scraped(conn, url):
            log.info("  → already in DB — skipping.")
            log_scrape(conn, url, "skip")
            skipped += 1
            continue

        soup = fetch(url)
        time.sleep(config.REQUEST_DELAY_SECONDS)

        if soup is None:
            log.error("  → fetch failed after %d retries.", config.MAX_RETRIES)
            log_scrape(conn, url, "error", ["fetch failed"])
            errors += 1
            continue

        try:
            remedy = parser_fn(url, soup)
        except Exception as exc:
            log.exception("  → parser error: %s", exc)
            log_scrape(conn, url, "error", [f"parser crash: {exc}"])
            errors += 1
            continue

        if remedy is None:
            log.warning("  → parser returned None.")
            log_scrape(conn, url, "error", ["parser returned None"])
            errors += 1
            continue

        issues = quality_check(remedy)
        if issues:
            log.warning("  → QUALITY GATE FAILED — remedy NOT saved.")
            for issue in issues:
                log.warning("     ✗  %s", issue)
            log_scrape(conn, url, "error", issues)
            errors += 1
            continue

        try:
            save_remedy(conn, remedy)
        except Exception as exc:
            log.exception("  → DB save failed: %s", exc)
            conn.rollback()
            log_scrape(conn, url, "error", [f"db: {exc}"])
            errors += 1
            continue

        total_chars = (
            len(remedy.name) + len(remedy.common_name)
            + len(remedy.introduction)
            + sum(len(s.content) for s in remedy.sections)
        )
        log.info(
            "  ✓  '%s'  |  common: '%s'  |  %d sections  |  %d chars",
            remedy.name, remedy.common_name,
            len(remedy.sections), total_chars,
        )
        log_scrape(conn, url, "success")
        success += 1

    log.info("-" * 65)
    log.info(
        "%s  →  saved=%d  skipped=%d  errors=%d",
        label, success, skipped, errors,
    )
    return success, skipped, errors


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    conn = db_connect()
    gs = gsk = ge = 0

    if config.SCRAPE_MATERIAMEDICA:
        urls = mm_collect_urls()
        if urls:
            s, sk, e = run(conn, urls, mm_parse, "materiamedica.info")
            gs += s; gsk += sk; ge += e

    if config.SCRAPE_HOMEOINT:
        urls = hi_collect_urls()
        if urls:
            s, sk, e = run(conn, urls, hi_parse, "homeoint.org")
            gs += s; gsk += sk; ge += e

    log.info("=" * 65)
    log.info("ALL DONE  —  saved=%d  skipped=%d  errors=%d", gs, gsk, ge)
    log.info("=" * 65)
    conn.close()


if __name__ == "__main__":
    main()
