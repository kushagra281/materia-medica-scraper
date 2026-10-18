# materia-medica-scraper

Scrapes Boericke's Materia Medica and builds the tables the HomeoCare app searches.

Order of operations on Railway (set `SUPA_HOST`, `SUPA_USER`, `SUPA_PASSWORD`):

1. `python scraper.py` - scrape into the local Postgres (`remedies`, `remedy_sections`)
2. `python migrate_to_supabase.py` - copy to Supabase. **Empties `remedy_symptoms`** (foreign key cascade).
3. `python extract_symptoms.py` - rebuild `remedy_symptoms` from the sections
4. `python rebuild_rubrics.py` - rebuild `rubrics` / `rubric_remedies` from `remedy_symptoms`
   (they are derived from it; skipping this leaves them stale)

Tests (no database needed): `python test_extract_symptoms.py`
