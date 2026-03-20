"""
init_db.py
==========
Run this ONCE on Railway before running the scraper.
It creates all tables, indexes, and views from schema.sql.

Railway run command:  python init_db.py
"""

import sys
import psycopg2
import config

def main():
    try:
        conn = psycopg2.connect(**config.DB)
        conn.autocommit = True
        print(f"Connected to '{config.DB['dbname']}' on {config.DB['host']}")
    except psycopg2.OperationalError as exc:
        print(f"ERROR: Cannot connect to database — {exc}")
        sys.exit(1)

    with open("schema.sql", "r", encoding="utf-8") as f:
        sql = f.read()

    with conn.cursor() as cur:
        cur.execute(sql)

    print("✓ All tables, indexes and views created successfully.")
    print("  You can now run:  python scraper.py")
    conn.close()

if __name__ == "__main__":
    main()
