"""
extract_symptoms.py
-------------------
Reads remedy_sections from Supabase, splits each section content
into individual symptoms, and populates the remedy_symptoms table.

Run on Railway by setting start command to:
    python extract_symptoms.py

Environment variables needed (already set in Railway):
    SUPA_HOST, SUPA_USER, SUPA_PASSWORD
"""

import psycopg2
import psycopg2.extras
import os
import re

# ── SUPABASE connection ─────────────────────────────────────────
SUPABASE = {
    "host":     os.environ["SUPA_HOST"],
    "port":     int(os.environ.get("SUPA_PORT", 5432)),
    "dbname":   os.environ.get("SUPA_DATABASE", "postgres"),
    "user":     os.environ["SUPA_USER"],
    "password": os.environ["SUPA_PASSWORD"],
}

# Sections to skip — these are not symptoms
SKIP_HEADINGS = {
    "Relationship", "Dose", "Dose 2", "Non-Homeopathic Uses",
    "Antidotes", "Compare", "Complementary"
}


def split_symptoms(text: str) -> list[str]:
    """
    Split section content into individual symptoms.
    Each symptom is a meaningful clause ending with . or ;
    """
    if not text:
        return []

    # Split on period or semicolon followed by space and capital letter
    # or just on semicolons
    parts = re.split(r'(?<=[.;])\s+(?=[A-Z])|;\s*', text)

    symptoms = []
    for part in parts:
        part = part.strip().rstrip('.,;').strip()
        # Skip very short or empty parts
        if len(part) < 10:
            continue
        # Skip parts that are just references like (Ars; Plat)
        if part.startswith('(') and part.endswith(')'):
            continue
        symptoms.append(part)

    return symptoms


def run():
    print("Connecting to Supabase...")
    conn = psycopg2.connect(**SUPABASE)
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
    all_symptoms = []
    skipped_headings = set()

    for sec in sections:
        heading = sec["heading"]

        # Skip non-symptom sections
        if any(h.lower() in heading.lower() for h in SKIP_HEADINGS):
            skipped_headings.add(heading)
            continue

        symptoms = split_symptoms(sec["content"])

        for order, symptom in enumerate(symptoms, 1):
            all_symptoms.append((
                sec["remedy_id"],
                sec["remedy_name"],
                heading,
                symptom,
                order
            ))

    print(f"   Extracted {len(all_symptoms)} individual symptoms")
    print(f"   Skipped headings: {skipped_headings}")

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
