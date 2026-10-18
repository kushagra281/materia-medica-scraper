"""
Migration script: Railway PostgreSQL → Supabase
Run this ON Railway by setting start command to: python migrate_to_supabase.py
All credentials are read from Railway environment variables.
"""

import psycopg2
import psycopg2.extras
import os

# ── RAILWAY (source) — already available as env vars on Railway ─
RAILWAY = {
    "host":     os.environ["PGHOST"],
    "port":     int(os.environ["PGPORT"]),
    "dbname":   os.environ["PGDATABASE"],
    "user":     os.environ["PGUSER"],
    "password": os.environ["PGPASSWORD"],
}

# ── SUPABASE (destination) — add these in Railway Variables tab ─
SUPABASE = {
    "host":     os.environ["SUPA_HOST"],
    "port":     int(os.environ.get("SUPA_PORT", 5432)),
    "dbname":   os.environ.get("SUPA_DATABASE", "postgres"),
    "user":     os.environ["SUPA_USER"],
    "password": os.environ["SUPA_PASSWORD"],
}


def migrate():
    print("Connecting to Railway PostgreSQL (source)...")
    src = psycopg2.connect(**RAILWAY)
    src_cur = src.cursor(cursor_factory=psycopg2.extras.DictCursor)

    print("Connecting to Supabase (destination)...")
    dst = psycopg2.connect(**SUPABASE)
    dst_cur = dst.cursor()

    # ── 1. Migrate remedies ──────────────────────────────────────
    print("\nMigrating remedies...")
    src_cur.execute("""
        SELECT id, slug, name, common_name, introduction,
               source_site, source_url, section_count,
               total_chars, scraped_at
        FROM remedies ORDER BY id
    """)
    remedies = src_cur.fetchall()

    # CASCADE also empties remedy_symptoms (it references remedies). The app's remedy
    # search reads that table, so it MUST be rebuilt afterwards (see the message at the end).
    print("   NOTE: this also clears remedy_symptoms - run extract_symptoms.py afterwards.")
    dst_cur.execute(
        "TRUNCATE remedy_sections, remedies, scrape_log RESTART IDENTITY CASCADE"
    )

    psycopg2.extras.execute_batch(dst_cur, """
        INSERT INTO remedies
            (id, slug, name, common_name, introduction,
             source_site, source_url, section_count,
             total_chars, scraped_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (slug) DO UPDATE SET
            name          = EXCLUDED.name,
            common_name   = EXCLUDED.common_name,
            introduction  = EXCLUDED.introduction,
            source_url    = EXCLUDED.source_url,
            section_count = EXCLUDED.section_count,
            total_chars   = EXCLUDED.total_chars,
            scraped_at    = EXCLUDED.scraped_at
    """, [tuple(r) for r in remedies])

    print(f"   ✅ {len(remedies)} remedies migrated")

    # ── 2. Migrate remedy_sections ───────────────────────────────
    print("Migrating remedy sections...")
    src_cur.execute("""
        SELECT remedy_id, heading, heading_order, content, char_count
        FROM remedy_sections ORDER BY remedy_id, heading_order
    """)
    sections = src_cur.fetchall()

    psycopg2.extras.execute_batch(dst_cur, """
        INSERT INTO remedy_sections
            (remedy_id, heading, heading_order, content, char_count)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """, [tuple(s) for s in sections])

    print(f"   ✅ {len(sections)} sections migrated")

    # ── 3. Migrate scrape_log ────────────────────────────────────
    print("Migrating scrape log...")
    src_cur.execute("SELECT url, status, message, logged_at FROM scrape_log")
    logs = src_cur.fetchall()

    psycopg2.extras.execute_batch(dst_cur, """
        INSERT INTO scrape_log (url, status, message, logged_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """, [tuple(l) for l in logs])

    print(f"   ✅ {len(logs)} log entries migrated")

    dst.commit()
    src.close()
    dst.close()

    print("\n🎉 Migration complete!")
    print(f"   Remedies : {len(remedies)}")
    print(f"   Sections : {len(sections)}")
    print(f"   Logs     : {len(logs)}")
    print("\nAll data is now in Supabase!")
    print("NEXT STEP: run  python extract_symptoms.py  - remedy_symptoms was emptied by the")
    print("           migration and the app's search returns nothing until it is rebuilt.")


if __name__ == "__main__":
    migrate()
