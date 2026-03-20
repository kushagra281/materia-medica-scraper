"""
Homeopathic Materia Medica Scraper
====================================
Author  : <your name>
Sources : materiamedica.info  |  homeoint.org
Book    : William Boericke — Pocket Manual of Homoeopathic Materia Medica (1901)
DB      : PostgreSQL  (see schema.sql)

Run:
    python scraper.py

Install:
    pip install requests beautifulsoup4 psycopg2-binary
"""

import re
import sys
import time
import logging
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
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
# QUALITY GATE
# ═══════════════════════════════════════════════════════════════

def quality_check(remedy: Remedy) -> list[str]:
    """
    Run every quality rule against a Remedy object.

    Returns a list of issue strings.
    An EMPTY list means the remedy PASSED all checks.
    A non-empty list means it FAILED — the remedy is NOT saved.

    All thresholds live in config.py so they can be tuned
    without touching scraper logic.
    """
    issues: list[str] = []

    # ── 1. Name ─────────────────────────────────────────────────
    if not remedy.name:
        issues.append("MISSING: name is empty")
    elif len(remedy.name) < 2:
        issues.append(f"THIN: name is only {len(remedy.name)} char(s)")

    # ── 2. Common name ──────────────────────────────────────────
    if not remedy.common_name:
        issues.append("MISSING: common_name is empty")

    # ── 3. Introduction ─────────────────────────────────────────
    if not remedy.introduction:
        issues.append("MISSING: introduction paragraph is empty")
    elif len(remedy.introduction) < config.MIN_INTRODUCTION_CHARS:
        issues.append(
            f"THIN: introduction is {len(remedy.introduction)} chars "
            f"(minimum {config.MIN_INTRODUCTION_CHARS})"
        )

    # ── 4. Sections count ───────────────────────────────────────
    if not remedy.sections:
        issues.append("MISSING: no sections were extracted")
    elif len(remedy.sections) < config.MIN_SECTIONS_COUNT:
        issues.append(
            f"THIN: only {len(remedy.sections)} section(s) found "
            f"(minimum {config.MIN_SECTIONS_COUNT})"
        )

    # ── 5. Individual section content ───────────────────────────
    for s in remedy.sections:
        if not s.content:
            issues.append(f"EMPTY section: '{s.heading}' has no content")
        elif len(s.content) < config.MIN_SECTION_CHARS:
            issues.append(
                f"THIN section: '{s.heading}' is {len(s.content)} chars "
                f"(minimum {config.MIN_SECTION_CHARS})"
            )

    # ── 6. Total content volume ─────────────────────────────────
    total = (
        len(remedy.name)
        + len(remedy.common_name)
        + len(remedy.introduction)
        + sum(len(s.content) for s in remedy.sections)
    )
    if total < config.MIN_TOTAL_CHARS:
        issues.append(
            f"TOTAL CONTENT TOO SMALL: {total} chars "
            f"(minimum {config.MIN_TOTAL_CHARS})"
        )

    return issues


# ═══════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════

def db_connect() -> psycopg2.extensions.connection:
    try:
        conn = psycopg2.connect(**config.DB)
        conn.autocommit = False
        log.info("Connected to PostgreSQL '%s'.", config.DB["dbname"])
        return conn
    except psycopg2.OperationalError as exc:
        log.critical("PostgreSQL connection failed: %s", exc)
        sys.exit(1)


def url_already_scraped(conn, url: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM remedies WHERE source_url = %s", (url,))
        return cur.fetchone() is not None


def save_remedy(conn, remedy: Remedy) -> None:
    """
    Atomically upsert the remedy row and all its sections.
    Old sections are deleted and fully replaced on each upsert
    so the DB never contains stale partial data.
    """
    total_chars = (
        len(remedy.name)
        + len(remedy.common_name)
        + len(remedy.introduction)
        + sum(len(s.content) for s in remedy.sections)
    )

    with conn.cursor() as cur:
        # Upsert remedy
        cur.execute(
            """
            INSERT INTO remedies
                (slug, name, common_name, introduction,
                 source_site, source_url,
                 sections_count, total_chars)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_url) DO UPDATE SET
                name           = EXCLUDED.name,
                common_name    = EXCLUDED.common_name,
                introduction   = EXCLUDED.introduction,
                sections_count = EXCLUDED.sections_count,
                total_chars    = EXCLUDED.total_chars,
                scraped_at     = NOW()
            RETURNING id
            """,
            (
                remedy.slug,
                remedy.name,
                remedy.common_name,
                remedy.introduction,
                remedy.source_site,
                remedy.source_url,
                len(remedy.sections),
                total_chars,
            ),
        )
        remedy_id = cur.fetchone()[0]

        # Wipe old sections
        cur.execute(
            "DELETE FROM remedy_sections WHERE remedy_id = %s",
            (remedy_id,),
        )

        # Insert fresh sections
        if remedy.sections:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO remedy_sections
                    (remedy_id, heading, heading_order, content)
                VALUES %s
                """,
                [
                    (remedy_id, s.heading, s.order, s.content)
                    for s in remedy.sections
                ],
            )

    conn.commit()


def log_scrape(conn, url: str, status: str, issues: list[str] = None) -> None:
    """Write one audit row to scrape_log."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scrape_log (url, status, issues) VALUES (%s, %s, %s)",
            (url, status, issues or []),
        )
    conn.commit()


# ═══════════════════════════════════════════════════════════════
# HTTP
# ═══════════════════════════════════════════════════════════════

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (compatible; MateriaMedicaResearchBot/1.0; "
            "non-commercial educational scraper)"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml",
    }
)


def fetch(url: str) -> Optional[BeautifulSoup]:
    """
    Fetch a URL with exponential-back-off retry.
    Returns a BeautifulSoup object on success, None on permanent failure.
    """
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            resp = _SESSION.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as exc:
            log.warning(
                "  [%d/%d] fetch error: %s — %s",
                attempt, config.MAX_RETRIES, url, exc,
            )
            if attempt < config.MAX_RETRIES:
                time.sleep(2 ** attempt)   # 2s, 4s, 8s …
    return None


# ═══════════════════════════════════════════════════════════════
# SECTION PARSER  (shared by both sites — same book format)
# ═══════════════════════════════════════════════════════════════

# Boericke's format confirmed across 3 real pages:
#   "Mind.--Patient lives in a world..."
#   "Non-Homeopathic Uses.--Atropia and its salts..."
#   "Relationship.--Compare: Sanguisorba..."
#
# Pattern: one or more title-case words (may include spaces, hyphens,
#          slashes), then a literal ".--", then content on the same line.
_SECTION_RE = re.compile(
    r'^([A-Z][A-Za-z]*(?:[\s\-/][A-Za-z]+){0,5})\.--\s+(.+)'
)

# Lines that are navigation or footer noise — discard them from body text
_NOISE_LINE_RE = re.compile(
    r'more information and order|'
    r'Remedia Homeopathy|'
    r'Free Materia Medica|'
    r'Materia Medica by William Boericke|'
    r'This is a chapter|'
    r'powered by|'
    r'is available at Remedia|'
    r'Other names for this|'
    r'Manual potenti|'
    r'5,500 homeopathic|'
    r'66,000 customers|'
    r'excellent|'
    r'rating of the product|'
    r'Imprint|'
    r'Copyright\s*©',
    re.IGNORECASE,
)

# Stop accumulating text once we hit footer HTML tags
_FOOTER_TAGS = {"h4", "h3", "footer", "nav"}


def _clean(text: str) -> str:
    """Collapse runs of whitespace into single spaces and strip edges."""
    return re.sub(r'\s+', ' ', text).strip()


def extract_body_text(h1_tag: Tag) -> str:
    """
    Collect all text that follows the <h1> remedy title on the page,
    stopping when we hit an <h4> (the "available at Remedia" footer)
    or any other known footer tag.

    Returns raw multi-line text, with noise lines already removed.
    """
    lines: list[str] = []

    for el in h1_tag.next_siblings:
        # Stop at footer tags
        if isinstance(el, Tag) and el.name in _FOOTER_TAGS:
            break

        raw = (
            el.get_text(separator="\n")
            if isinstance(el, Tag)
            else str(el)
        )

        for line in raw.splitlines():
            stripped = line.strip()
            # Drop navigation and footer noise lines
            if stripped and _NOISE_LINE_RE.search(stripped):
                continue
            lines.append(stripped)

    return "\n".join(lines)


def parse_body(body_text: str) -> tuple[str, list[Section]]:
    """
    Split raw body text into:
      introduction  — paragraphs before the first "Heading.--" marker
      sections      — list of Section in document order

    Rules (derived from actual Boericke pages):
    - Lines matching _SECTION_RE start a new section.
    - All lines before the first matching line = introduction.
    - Section content accumulates on subsequent lines until the next match.
    - Blank lines are kept as paragraph separators within sections.
    - Content is cleaned (collapsed whitespace) before storage.
    """
    intro_lines:   list[str] = []
    sections:      list[Section] = []
    cur_heading:   Optional[str] = None
    cur_lines:     list[str] = []
    order:         int = 0
    in_intro:      bool = True

    def _flush_section():
        nonlocal cur_heading, cur_lines
        if cur_heading is None:
            return
        content = _clean(" ".join(l for l in cur_lines if l))
        if content:
            sections.append(Section(
                heading=cur_heading,
                order=order,
                content=content,
            ))
        cur_heading = None
        cur_lines = []

    for line in body_text.splitlines():
        line = line.strip()

        if not line:
            # Preserve blank line as paragraph separator
            if in_intro:
                intro_lines.append("")
            else:
                cur_lines.append("")
            continue

        m = _SECTION_RE.match(line)
        if m:
            # Flush whatever was accumulating
            if in_intro:
                # Move trailing blank lines out of intro
                while intro_lines and not intro_lines[-1]:
                    intro_lines.pop()
            else:
                _flush_section()

            in_intro = False
            order += 1
            cur_heading = m.group(1).strip()
            # The rest of the line is the first content of this section
            first = m.group(2).strip()
            cur_lines = [first] if first else []

        else:
            if in_intro:
                intro_lines.append(line)
            else:
                cur_lines.append(line)

    # Flush final section
    _flush_section()

    introduction = _clean(" ".join(l for l in intro_lines if l))
    return introduction, sections


# ═══════════════════════════════════════════════════════════════
# SOURCE 1 — materiamedica.info
# ═══════════════════════════════════════════════════════════════

def mm_collect_urls() -> list[str]:
    """
    The index page lists every remedy as a hyperlink.
    Pattern confirmed: /en/materia-medica/william-boericke/<slug>
    """
    log.info("Collecting remedy URLs from materiamedica.info …")
    soup = fetch(config.MATERIAMEDICA_INDEX)
    if soup is None:
        log.error("Cannot load materiamedica.info index. Skipping source.")
        return []

    urls: list[str] = []
    for a in soup.select("a[href]"):
        href = a["href"].strip()
        if re.match(
            r'^/en/materia-medica/william-boericke/[a-z0-9][a-z0-9\-]+$',
            href,
        ):
            full = config.MATERIAMEDICA_BASE + href
            if full not in urls:
                urls.append(full)

    log.info("  → %d remedy URLs found.", len(urls))
    return urls


def mm_parse(url: str, soup: BeautifulSoup) -> Optional[Remedy]:
    """
    Parse one materiamedica.info remedy page.

    Structure confirmed on Arsenicum Album, Belladonna, Nux Vomica:
      <h1>  REMEDY NAME (ALL CAPS)  </h1>
      <a>   more information and order at Remedia Homeopathy  </a>
      [text node or <br>]  Common Name (e.g. "Deadly Nightshade")
      [blank line]
      Introduction paragraph(s)
      Mind.--...
      Head.--...
      ...
      Dose.--...
      <h4>  Latin name is available at Remedia Homeopathy  </h4>
      (FOOTER — stop here)
    """
    slug = url.rstrip("/").split("/")[-1]

    # ── 1. Remedy name ──────────────────────────────────────────
    h1 = soup.find("h1")
    if h1 is None:
        log.warning("  No <h1> found: %s", url)
        return None
    name = _clean(h1.get_text())
    if not name:
        log.warning("  Empty <h1>: %s", url)
        return None

    # ── 2. Body text (after <h1>, before <h4> footer) ───────────
    body_text = extract_body_text(h1)

    # ── 3. Common name ──────────────────────────────────────────
    # The common name is the FIRST non-blank, non-section-heading line
    # in the body. "more information" lines are already stripped by
    # extract_body_text / _NOISE_LINE_RE.
    common_name = ""
    cleaned_body_lines: list[str] = []
    found_common = False

    for line in body_text.splitlines():
        stripped = line.strip()
        if not found_common:
            if not stripped:
                continue
            if _SECTION_RE.match(stripped):
                # No common name — sections start immediately
                found_common = True
                cleaned_body_lines.append(stripped)
            else:
                common_name = _clean(stripped)
                found_common = True
                # Do NOT add the common name into the body text;
                # it lives in its own DB column.
        else:
            cleaned_body_lines.append(line)

    body_text = "\n".join(cleaned_body_lines)

    # ── 4. Introduction + Sections ──────────────────────────────
    introduction, sections = parse_body(body_text)

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
    """
    homeoint.org uses one letter page per letter (a.htm … z.htm).
    Remedy links look like: href="a/abiesc.htm"
    """
    log.info("Collecting remedy URLs from homeoint.org …")
    all_urls: list[str] = []

    for letter in config.HOMEOINT_LETTERS:
        page_url = config.HOMEOINT_BASE + f"{letter}.htm"
        soup = fetch(page_url)
        time.sleep(config.REQUEST_DELAY_SECONDS)
        if soup is None:
            log.warning("  Cannot load letter page '%s' — skipping.", letter)
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
    """
    Parse one homeoint.org remedy page.

    homeoint uses older HTML but the same Boericke text format.
    The remedy name is in <h1> or <h2>; body follows the same
    "Heading.--  content" pattern.
    """
    slug = url.rstrip("/").split("/")[-1].replace(".htm", "")

    # ── 1. Remedy name ──────────────────────────────────────────
    name = ""
    name_tag = None
    for tag_name in ("h1", "h2", "h3"):
        el = soup.find(tag_name)
        if el:
            candidate = _clean(el.get_text())
            # Reject obviously wrong matches (e.g. site nav headings)
            if candidate and len(candidate) < 120 and not candidate.startswith("H.I."):
                name = candidate
                name_tag = el
                break

    if not name:
        log.warning("  No heading found for %s", url)
        return None

    # ── 2. Body text ────────────────────────────────────────────
    # homeoint doesn't have a clean <h4> footer marker,
    # so we use the full body text and strip known noise.
    body = soup.body if soup.body else soup
    raw_text = body.get_text(separator="\n")

    # Remove page header above the remedy name
    # (everything up to and including the name line)
    name_pos = raw_text.find(name)
    if name_pos != -1:
        raw_text = raw_text[name_pos + len(name):]

    # Strip noise lines
    clean_lines: list[str] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped and _NOISE_LINE_RE.search(stripped):
            continue
        # homeoint-specific footer markers
        if re.search(
            r'M[eé]di-T|Click HERE|Buy a copy|Norwegian|Norv[eé]gian|'
            r'Presented by|H\.I\. English|Remerciements',
            stripped, re.IGNORECASE,
        ):
            break  # stop reading
        clean_lines.append(stripped)

    body_text = "\n".join(clean_lines)

    # ── 3. Common name ──────────────────────────────────────────
    common_name = ""
    final_lines: list[str] = []
    found_common = False

    for line in body_text.splitlines():
        stripped = line.strip()
        if not found_common:
            if not stripped:
                continue
            if _SECTION_RE.match(stripped):
                found_common = True
                final_lines.append(stripped)
            else:
                common_name = _clean(stripped)
                found_common = True
        else:
            final_lines.append(line)

    body_text = "\n".join(final_lines)

    # ── 4. Introduction + Sections ──────────────────────────────
    introduction, sections = parse_body(body_text)

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
# SCRAPE RUNNER — generic for both sources
# ═══════════════════════════════════════════════════════════════

def run(conn, urls: list[str], parser_fn, label: str) -> tuple[int, int, int]:
    """
    Iterate over URLs:
      1. Skip if already in DB
      2. Fetch HTML
      3. Parse into Remedy
      4. Quality-gate — log and reject if any check fails
      5. Save to DB

    Returns (success, skipped, errors).
    """
    total   = len(urls)
    success = skipped = errors = 0

    log.info("=" * 65)
    log.info("START  %s  (%d URLs)", label, total)
    log.info("=" * 65)

    for i, url in enumerate(urls, start=1):
        log.info("[%d/%d]  %s", i, total, url)

        # ── Already done? ────────────────────────────────────────
        if url_already_scraped(conn, url):
            log.info("  → already in DB — skipping.")
            log_scrape(conn, url, "skip")
            skipped += 1
            continue

        # ── Fetch ─────────────────────────────────────────────────
        soup = fetch(url)
        time.sleep(config.REQUEST_DELAY_SECONDS)

        if soup is None:
            log.error("  → FETCH FAILED after %d retries.", config.MAX_RETRIES)
            log_scrape(conn, url, "error", ["fetch failed"])
            errors += 1
            continue

        # ── Parse ─────────────────────────────────────────────────
        try:
            remedy = parser_fn(url, soup)
        except Exception as exc:
            log.exception("  → PARSER CRASH: %s", exc)
            log_scrape(conn, url, "error", [f"parser crash: {exc}"])
            errors += 1
            continue

        if remedy is None:
            log.warning("  → Parser returned None — no data extracted.")
            log_scrape(conn, url, "error", ["parser returned None"])
            errors += 1
            continue

        # ── Quality gate ──────────────────────────────────────────
        issues = quality_check(remedy)
        if issues:
            log.warning("  → QUALITY GATE FAILED — remedy NOT saved.")
            for issue in issues:
                log.warning("     ✗  %s", issue)
            log_scrape(conn, url, "error", issues)
            errors += 1
            continue

        # ── Save ──────────────────────────────────────────────────
        try:
            save_remedy(conn, remedy)
        except Exception as exc:
            log.exception("  → DB SAVE FAILED: %s", exc)
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
            remedy.name,
            remedy.common_name,
            len(remedy.sections),
            total_chars,
        )
        log_scrape(conn, url, "success")
        success += 1

    log.info("-" * 65)
    log.info(
        "%s  →  saved: %d  |  skipped: %d  |  errors: %d",
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
    log.info(
        "ALL DONE  —  saved: %d  |  skipped: %d  |  errors: %d",
        gs, gsk, ge,
    )
    log.info("=" * 65)
    conn.close()


if __name__ == "__main__":
    main()
