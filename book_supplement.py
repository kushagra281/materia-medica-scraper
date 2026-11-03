"""
Adds remedies that materiamedica.info's index does not list (Aconitum napellus, Abrotanum,
Allium cepa, Colocynthis, Cimicifuga, ...).

The text comes from data/boericke_supplement.json: those remedies taken from the public-domain
text of William Boericke's "Pocket Manual of Homoeopathic Materia Medica" (1901), as published at
https://github.com/sudhirbrahma/boericke-materia-medica. Only remedies that are NOT already in the
database (matched by name) are added, so running this twice changes nothing.
"""
import json
import logging
import re
from pathlib import Path

import scraper

log = logging.getLogger("book_supplement")
SOURCE_SITE = "boericke-book"
DATA_FILE = Path(__file__).parent / "data" / "boericke_supplement.json"


def norm(name: str) -> str:
    return re.sub(r"[^A-Z]", "", name.upper())


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def build_remedy(entry: dict) -> scraper.Remedy:
    intro, sections = scraper.parse_sections("\n".join(entry["lines"]))
    # Prose-only entries (no "Mind.--" labels) are kept as one searchable section.
    # An entry the book itself gives in one short sentence is marked "allow_short" in the data file.
    if not sections and (len(intro) >= 150 or (entry.get("allow_short") and intro)):
        sections = [scraper.Section(heading="Description", order=1, content=intro)]
        intro = ""
    slug = slugify(entry["name"])
    return scraper.Remedy(
        slug=slug,
        name=entry["name"],
        common_name=entry.get("common", ""),
        introduction=intro,
        sections=sections,
        source_site=SOURCE_SITE,
        source_url=f"boericke-book:{slug}",
    )


def blocking_for(entry: dict, remedy: scraper.Remedy, issues: list[str]) -> list[str]:
    blocking = scraper.blocking_issues(remedy, issues)
    if entry.get("allow_short"):
        # The book has only this short text for the remedy; the size guard exists for failed scrapes.
        blocking = [b for b in blocking if not b.startswith("TOTAL TOO SMALL")]
    return blocking


def main() -> None:
    entries = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    conn = scraper.db_connect()
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM remedies")
        have = {norm(r[0]) for r in cur.fetchall()}
    added = skipped = refused = 0
    for entry in entries:
        if norm(entry["name"]) in have:
            skipped += 1
            continue
        remedy = build_remedy(entry)
        issues = scraper.quality_check(remedy)
        blocking = blocking_for(entry, remedy, issues)
        if blocking:
            log.warning("refused %s: %s", remedy.name, " | ".join(blocking))
            scraper.log_scrape(conn, remedy.source_url, "error", blocking)
            refused += 1
            continue
        scraper.save_remedy(conn, remedy)
        scraper.log_scrape(conn, remedy.source_url, "success",
                           ["saved with warnings: " + " | ".join(issues)] if issues else None)
        log.info("added %s (%d sections)", remedy.name, len(remedy.sections))
        added += 1
    log.info("book supplement: added=%d already-present=%d refused=%d", added, skipped, refused)
    conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
