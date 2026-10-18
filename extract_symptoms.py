"""
extract_symptoms.py
-------------------
Reads remedy_sections from Supabase, splits each section content
into individual symptoms, and populates the remedy_symptoms table.

Run on Railway by setting start command to:
    python extract_symptoms.py

Environment variables needed (already set in Railway):
    SUPA_HOST, SUPA_USER, SUPA_PASSWORD

Changes vs. the previous version
    * short symptoms (Vertigo, Nausea, Colic, Cramps ...) are KEPT. The old
      10-character minimum silently dropped exactly the one-word complaints
      patients type.
    * a modality fragment ("better, warmth", "worse, night") stays attached to
      the complaint it modifies instead of becoming a separate row.
    * remedy names get one canonical spelling, and the same sentence scraped from
      both source sites (materiamedica.info and homeoint.org) is stored once, so
      the app no longer double-counts it or lists a remedy twice.
    * environment variables are read in run(), so the helpers can be imported
      and tested without a database.
"""

import os
import re

# Sections to skip — these are not symptoms
SKIP_HEADINGS = {
    "Relationship", "Dose", "Dose 2", "Non-Homeopathic Uses",
    "Antidotes", "Compare", "Complementary"
}

# Shortest fragment kept. 4 keeps "Colic", "Cough", "Thirst" but drops stray 1-3 letter bits.
MIN_SYMPTOM_CHARS = 4

# Fragments that are never symptoms.
JUNK_FRAGMENTS = {"also", "see", "and", "etc", "cf", "compare", "none", "mind", "head"}

# A fragment starting with one of these modifies the previous fragment.
_MODALITY_START = re.compile(r'^(?:worse|better|aggravated|ameliorated)\b|^[<>]', re.IGNORECASE)


def _protect_parens(text: str) -> str:
    """Hide '.' and ';' that sit inside parentheses so references such as
    "(Ars; Plat)" or "(compare Ars.; Plat.)" are not torn apart by the splitter."""
    out: list[str] = []
    depth = 0
    for ch in text:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth = max(0, depth - 1)
        if depth > 0 and ch == ';':
            out.append('\x00')
        elif depth > 0 and ch == '.':
            out.append('\x01')
        else:
            out.append(ch)
    return ''.join(out)


def _restore_parens(text: str) -> str:
    return text.replace('\x00', ';').replace('\x01', '.')


def split_symptoms(text: str) -> list[str]:
    """
    Split section content into individual symptoms.
    Each symptom is a meaningful clause ending with . or ;
    Modality fragments ("better, warmth") are merged into the preceding complaint.
    Separators inside parentheses never split.
    """
    if not text:
        return []

    # Split on period or semicolon followed by space and capital letter
    # or just on semicolons
    parts = re.split(r'(?<=[.;])\s+(?=[A-Z])|;\s*', _protect_parens(text))

    merged: list[str] = []
    for part in parts:
        part = _restore_parens(part).strip().rstrip('.,;').strip()
        if not part:
            continue
        if merged and _MODALITY_START.match(part):
            merged[-1] = f"{merged[-1]}; {part}"
            continue
        merged.append(part)

    symptoms = []
    for part in merged:
        if len(part) < MIN_SYMPTOM_CHARS:
            continue
        if not re.search(r'[A-Za-z]{3}', part):
            continue
        if part.lower() in JUNK_FRAGMENTS:
            continue
        # Skip parts that are just references like (Ars; Plat)
        if part.startswith('(') and part.endswith(')'):
            continue
        symptoms.append(part)

    return symptoms


def clean_name(name: str) -> str:
    """Collapse whitespace and strip trailing punctuation from a remedy name."""
    return re.sub(r'\s+', ' ', name or '').strip().rstrip('.,;:').strip()


def name_key(name: str) -> str:
    """Case/punctuation-insensitive key: 'ARSENICUM ALBUM.' == 'Arsenicum  album'."""
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', ' ', clean_name(name).lower())).strip()


def build_rows(sections) -> tuple[list[tuple], dict]:
    """
    Turn (remedy_id, remedy_name, heading, content) section rows into
    remedy_symptoms rows, canonicalising names and removing duplicates.
    Returns (rows, stats).
    """
    canonical: dict[str, str] = {}   # name_key -> first-seen clean name
    seen: set[tuple[str, str]] = set()
    rows: list[tuple] = []
    skipped_headings: set[str] = set()
    duplicates = 0

    for sec in sections:
        heading = sec["heading"]

        # Skip non-symptom sections
        if any(h.lower() in heading.lower() for h in SKIP_HEADINGS):
            skipped_headings.add(heading)
            continue

        key = name_key(sec["remedy_name"])
        if not key:
            continue
        name = canonical.setdefault(key, clean_name(sec["remedy_name"]))

        for order, symptom in enumerate(split_symptoms(sec["content"]), 1):
            sig = (key, re.sub(r'\s+', ' ', symptom.lower()))
            if sig in seen:
                duplicates += 1
                continue
            seen.add(sig)
            rows.append((sec["remedy_id"], name, heading, symptom, order))

    stats = {
        "skipped_headings": skipped_headings,
        "duplicates_removed": duplicates,
        "distinct_remedies": len(canonical),
    }
    return rows, stats


def run():
    import psycopg2
    import psycopg2.extras

    supabase = {
        "host":     os.environ["SUPA_HOST"],
        "port":     int(os.environ.get("SUPA_PORT", 5432)),
        "dbname":   os.environ.get("SUPA_DATABASE", "postgres"),
        "user":     os.environ["SUPA_USER"],
        "password": os.environ["SUPA_PASSWORD"],
    }

    print("Connecting to Supabase...")
    conn = psycopg2.connect(**supabase)
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Create remedy_symptoms table if not exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS remedy_symptoms (
            id            SERIAL   PRIMARY KEY,
            remedy_id     INT      NOT NULL REFERENCES remedies(id) ON DELETE CASCADE,
            remedy_name   TEXT     NOT NULL,
            heading       TEXT     NOT NULL,
            symptom       TEXT     NOT NULL,
            symptom_order SMALLINT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sym_remedy_id ON remedy_symptoms (remedy_id);
        CREATE INDEX IF NOT EXISTS idx_sym_heading   ON remedy_symptoms (heading);
        CREATE INDEX IF NOT EXISTS idx_sym_fts       ON remedy_symptoms
            USING GIN (to_tsvector('english', symptom));
    """)

    # Clear existing symptoms
    print("Clearing old symptoms...")
    cur.execute("TRUNCATE remedy_symptoms RESTART IDENTITY")

    # Fetch all sections with remedy name
    print("Fetching sections from Supabase...")
    cur.execute("""
        SELECT rs.remedy_id, r.name as remedy_name,
               rs.heading, rs.content
        FROM remedy_sections rs
        JOIN remedies r ON r.id = rs.remedy_id
        ORDER BY rs.remedy_id, rs.heading_order
    """)
    sections = cur.fetchall()
    print(f"   Found {len(sections)} sections")

    # Extract and insert symptoms
    all_symptoms, stats = build_rows(sections)

    print(f"   Extracted {len(all_symptoms)} individual symptoms "
          f"for {stats['distinct_remedies']} distinct remedies")
    print(f"   Duplicate sentences removed: {stats['duplicates_removed']}")
    print(f"   Skipped headings: {stats['skipped_headings']}")

    # Batch insert
    print("Inserting symptoms into Supabase...")
    psycopg2.extras.execute_batch(cur, """
        INSERT INTO remedy_symptoms
            (remedy_id, remedy_name, heading, symptom, symptom_order)
        VALUES (%s, %s, %s, %s, %s)
    """, all_symptoms, page_size=500)

    conn.commit()
    conn.close()

    print(f"\n🎉 Done!")
    print(f"   Total symptoms extracted: {len(all_symptoms)}")
    print(f"\nExample query to search symptoms:")
    print("""
    SELECT remedy_name, heading, symptom
    FROM remedy_symptoms
    WHERE symptom ILIKE '%headache%'
    ORDER BY remedy_name;
    """)


if __name__ == "__main__":
    run()
