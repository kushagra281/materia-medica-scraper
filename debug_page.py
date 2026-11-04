"""Shows what the scraper makes of ONE page, without touching the database.

    python debug_page.py https://www.materiamedica.info/en/materia-medica/william-boericke/strychninum-phosphoricum

Prints the text after the <h1> line by line (with lengths), then the parsed sections, the total
size and the quality issues. Used to find out why a page is read as too short.
"""
import sys
import scraper


def main(url: str) -> int:
    soup = scraper.fetch(url)
    if soup is None:
        print("FETCH FAILED"); return 1
    h1 = soup.find("h1")
    print("H1:", h1.get_text(strip=True) if h1 else None)
    body = scraper.get_text_after_h1(soup)
    print(f"\n--- text after <h1>: {len(body)} chars, {len(body.splitlines())} lines ---")
    for i, line in enumerate(body.splitlines()[:60]):
        print(f"{i:3d} [{len(line):4d}] {line[:160]}")
    remedy = scraper.mm_parse(url, soup)
    if remedy is None:
        print("\nmm_parse returned None"); return 0
    total = len(remedy.introduction) + sum(len(s.content) for s in remedy.sections)
    print(f"\n--- parsed: name={remedy.name!r} common={remedy.common_name!r} intro={len(remedy.introduction)} chars, {len(remedy.sections)} sections, total {total} ---")
    for s in remedy.sections:
        print(f"  {s.order:2d}. {s.heading!r}: {len(s.content)} chars  {s.content[:100]!r}")
    issues = scraper.quality_check(remedy)
    print("\nissues:", issues)
    print("blocking:", scraper.blocking_issues(remedy, issues))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else
                  "https://www.materiamedica.info/en/materia-medica/william-boericke/strychninum-phosphoricum"))
