"""
import_repertory.py
-------------------
Loads a GRADED repertory into the repertory_* tables (see repertory_schema.sql).

Source of the data: https://github.com/drsamonline/homoeopathic-materia-medica-repertory-json
(`repertory/<book>/*.json`). The data is NOT stored in this repository: the workflow checks it out at
run time and this script only reads it.

    python import_repertory.py --data-dir ../repertory-data --book repertorium-publicum-2008 --dry-run
    python import_repertory.py --data-dir ../repertory-data --book repertorium-publicum-2008

Why a new set of tables: the existing `rubrics` / `rubric_remedies` are derived from the
materia medica sentences and every grade in them is 1. A real repertory has a rubric TREE and
printed grades 1-3; those are what repertorisation needs.

Which books: only the ones listed in BOOKS, because each one needs its licence and credit recorded
with it. Other books in that repository either carry no grades (Kent 1897) or have unreliable OCR
(Knerr 1896); they can be added here later with their own entry.

Environment (not needed for --dry-run): PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD
(or SUPA_HOST ... like the other scripts here).
"""

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter

BOOKS = {
    "repertorium-publicum-2008": {
        "title": "Repertorium Publicum",
        "author": "Vladimir Polony",
        "year": 2008,
        "licence": "GNU GPL v3",
        "source_url": "https://github.com/nondeterministic/oorep",
        "attribution": (
            "Repertorium Publicum (2008) by Vladimir Polony, part of the OpenRep project, "
            "licensed under the GNU GPL v3. Compiled as JSON by Dr Sohil Momin."
        ),
        "note": (
            "A Kent-derived open repertory with its own chapters and additions. "
            "It is not Kent's 1897 first edition."
        ),
        "graded": True,
        "id_base": 1_000_000,
    },
}

ID_RE = re.compile(r"-r(\d+)$")
MAX_DEPTH = 40          # a chain longer than this is a loop or corrupt data


class ImportProblem(Exception):
    pass


def _clean(text):
    """Postgres rejects NUL characters; also collapse stray whitespace."""
    return re.sub(r"\s+", " ", (text or "").replace("\x00", " ")).strip()


def _number(rubric_id):
    m = ID_RE.search(rubric_id or "")
    return int(m.group(1)) if m else None


def load_records(data_dir, slug):
    """All rubric dicts of one book, from every chapter file (index.json is skipped)."""
    folder = os.path.join(data_dir, "repertory", slug)
    files = sorted(p for p in glob.glob(os.path.join(folder, "*.json")) if os.path.basename(p) != "index.json")
    if not files:
        raise ImportProblem(f"no chapter files found in {folder}")
    records = []
    for path in files:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if doc.get("type") != "repertory":
            raise ImportProblem(f"{path}: not a repertory file")
        section = doc.get("section")
        if not isinstance(section, dict):
            raise ImportProblem(f"{path}: expected a single 'section' object")
        records.extend(section.get("rubrics") or [])
    return records


def build(slug, records):
    """
    Turns raw rubric dicts into table rows.
    Returns (rubric_rows, remedy_rows, stats). Rows are plain tuples/dicts, no database needed.
    """
    meta = BOOKS[slug]
    base = meta["id_base"]
    problems = Counter()   # data we could not use as given: stops the load
    notes = Counter()      # harmless, already handled: only reported

    by_num = {}
    for r in records:
        n = _number(r.get("id"))
        if n is None:
            problems["rubric id without a number"] += 1
            continue
        if n in by_num:
            problems["duplicate rubric id"] += 1
            continue
        by_num[n] = r

    def parent_num(r):
        p = r.get("parent")
        if not p:
            return None
        pn = _number(p)
        if pn is None or pn not in by_num:
            problems["parent not found (treated as a chapter)"] += 1
            return None
        return pn

    parents = {n: parent_num(r) for n, r in by_num.items()}

    # Walk each rubric to its root once; memoise chapter, path and depth.
    memo = {}

    def resolve(n):
        chain = []
        cur = n
        while cur is not None and cur not in memo:
            if len(chain) >= MAX_DEPTH or cur in chain:
                problems["loop or too deep (cut)"] += 1
                break
            chain.append(cur)
            cur = parents[cur]
        base_path, base_depth, chapter = ([], -1, None)
        if cur is not None and cur in memo:
            base_path, base_depth, chapter = memo[cur]
        for node in reversed(chain):
            text = _clean(by_num[node].get("text")) or "(blank)"
            base_path = base_path + [text]
            base_depth += 1
            chapter = chapter or text
            memo[node] = (base_path, base_depth, chapter)
        return memo[n]

    children = Counter(p for p in parents.values() if p is not None)
    remedy_names = {}
    remedy_name_votes = {}
    link_counts = Counter()
    rubric_rows = []
    links = 0

    for n in sorted(by_num):
        r = by_num[n]
        path, depth, chapter = resolve(n)
        packed = {}
        for x in r.get("remedies") or []:
            abbrev = _clean(x.get("abbrev"))
            grade = x.get("grade")
            if not abbrev:
                problems["remedy without an abbreviation"] += 1
                continue
            if not isinstance(grade, int) or isinstance(grade, bool) or not 1 <= grade <= 3:
                problems["link without a grade 1-3 (skipped)"] += 1
                continue
            if abbrev in packed:
                notes["remedy listed twice in a rubric (highest grade kept)"] += 1
                packed[abbrev] = max(packed[abbrev], grade)
                continue
            packed[abbrev] = grade
            name = _clean(x.get("name"))
            if name:
                remedy_name_votes.setdefault(abbrev, Counter())[name] += 1
        for abbrev in packed:
            link_counts[abbrev] += 1
        links += len(packed)
        rubric_rows.append((
            base + n,                                   # id
            slug,                                       # source
            (base + parents[n]) if parents[n] is not None else None,
            chapter,
            path[-1],                                   # rubric_text
            " > ".join(path),                           # full_path
            depth,
            len(packed),
            children.get(n, 0),
            packed,
        ))

    for abbrev, votes in remedy_name_votes.items():
        if len(votes) > 1:
            notes["abbreviation with more than one name (most common kept)"] += 1
        remedy_names[abbrev] = votes.most_common(1)[0][0]
    remedy_rows = []
    for abbrev, count in sorted(link_counts.items()):
        remedy_rows.append((slug, abbrev, remedy_names.get(abbrev) or abbrev, count))

    stats = {
        "rubrics": len(rubric_rows),
        "links": links,
        "remedies": len(remedy_rows),
        "chapters": sum(1 for row in rubric_rows if row[2] is None),
        "max_depth": max((row[6] for row in rubric_rows), default=0),
        "problems": dict(problems),
        "notes": dict(notes),
    }
    return rubric_rows, remedy_rows, stats


def write(conn, slug, rubric_rows, remedy_rows, stats):
    """Replaces the book's rows in ONE transaction: the app never sees a half-loaded book."""
    from psycopg2.extras import Json, execute_values

    meta = BOOKS[slug]
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "repertory_schema.sql"), encoding="utf-8") as fh:
        schema = fh.read()

    cur = conn.cursor()
    cur.execute(schema)
    cur.execute("DELETE FROM repertory_sources WHERE slug = %s", (slug,))   # cascades to rubrics + remedies
    cur.execute(
        """INSERT INTO repertory_sources
             (slug, title, author, year, licence, source_url, attribution, note, graded, id_base,
              rubric_count, link_count)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (slug, meta["title"], meta["author"], meta["year"], meta["licence"], meta["source_url"],
         meta["attribution"], meta["note"], meta["graded"], meta["id_base"],
         stats["rubrics"], stats["links"]),
    )
    execute_values(
        cur,
        "INSERT INTO repertory_remedies (source, abbrev, name, link_count) VALUES %s",
        remedy_rows,
        page_size=1000,
    )
    # Parents first is not required (no foreign key between rubrics), so one pass is enough.
    execute_values(
        cur,
        """INSERT INTO repertory_rubrics
             (id, source, parent_id, chapter, rubric_text, full_path, depth, n_remedies, child_count, remedies)
           VALUES %s""",
        [row[:-1] + (Json(row[-1]),) for row in rubric_rows],
        page_size=1000,
    )
    cur.execute("SELECT count(*) FROM repertory_rubrics WHERE source = %s", (slug,))
    stored = cur.fetchone()[0]
    if stored != stats["rubrics"]:
        raise ImportProblem(f"stored {stored} rubrics but built {stats['rubrics']} - rolled back")
    conn.commit()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", required=True, help="folder holding repertory/<book>/*.json")
    ap.add_argument("--book", required=True, choices=sorted(BOOKS))
    ap.add_argument("--dry-run", action="store_true", help="parse and check only; do not touch the database")
    ap.add_argument("--allow-problems", action="store_true",
                    help="load even if the data had problems (they are always printed)")
    args = ap.parse_args(argv)

    records = load_records(args.data_dir, args.book)
    rubric_rows, remedy_rows, stats = build(args.book, records)

    print(f"book      : {args.book}  ({BOOKS[args.book]['licence']})")
    print(f"rubrics   : {stats['rubrics']:,}  (chapters {stats['chapters']}, deepest level {stats['max_depth']})")
    print(f"links     : {stats['links']:,}")
    print(f"remedies  : {stats['remedies']:,}")
    for row in rubric_rows[:: max(1, len(rubric_rows) // 5)][:5]:
        print(f"  e.g. {row[5]!s:70.70} [{row[7]} remedies]")
    for label, key in (("notes", "notes"), ("problems", "problems")):
        if stats[key]:
            print(f"{label:<10}:")
            for k, v in sorted(stats[key].items()):
                print(f"  {v:>7,}  {k}")

    if args.dry_run:
        print("dry run - nothing written")
        return 0
    if stats["problems"] and not args.allow_problems:
        print("Refusing to load data with problems (use --allow-problems after reading them).", file=sys.stderr)
        return 1
    if not stats["rubrics"]:
        print("Nothing to load.", file=sys.stderr)
        return 1

    import psycopg2

    def env(*names):
        for n in names:
            if os.environ.get(n):
                return os.environ[n]
        raise SystemExit(f"missing environment variable {names[0]}")

    conn = psycopg2.connect(
        host=env("PGHOST", "SUPA_HOST"),
        port=int(os.environ.get("PGPORT") or os.environ.get("SUPA_PORT") or 5432),
        dbname=os.environ.get("PGDATABASE") or os.environ.get("SUPA_DATABASE") or "postgres",
        user=env("PGUSER", "SUPA_USER"),
        password=env("PGPASSWORD", "SUPA_PASSWORD"),
    )
    try:
        write(conn, args.book, rubric_rows, remedy_rows, stats)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f"loaded {stats['rubrics']:,} rubrics, {stats['links']:,} links, {stats['remedies']:,} remedies")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ImportProblem as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
