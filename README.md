# materia-medica-scraper

Scrapes Boericke's Materia Medica and builds the tables the HomeoCare app searches.

Order of operations on Railway (set `SUPA_HOST`, `SUPA_USER`, `SUPA_PASSWORD`):

1. `python scraper.py` - scrape into the local Postgres (`remedies`, `remedy_sections`)
2. `python migrate_to_supabase.py` - copy to Supabase. **Empties `remedy_symptoms`** (foreign key cascade).
3. `python extract_symptoms.py` - rebuild `remedy_symptoms` from the sections
4. `python rebuild_rubrics.py` - rebuild `rubrics` / `rubric_remedies` from `remedy_symptoms`
   (they are derived from it; skipping this leaves them stale)

## One-time repair of the existing data

The first scrape had three problems (found by checking the live database):

- `common_name` is "Materia Medica" for all 476 remedies and every introduction starts with the
  site's navigation - the parser looked for the remedy name in the page `<title>` instead of the `<h1>`.
- 144 of the 620 remedy pages were never saved ("no sections extracted"), e.g. Arnica montana -
  most likely because their section labels sit in their own tag and the label regex needed text on
  the same line. This is fixed in the parser and covered by tests, but **I could not reach the live
  site from my environment, so please check the log after the run** (`scrape_log`, status `error`).
- `remedy_sections.char_count` was never copied by the migration (all 0).

To repair: run with `FORCE_REFRESH=1 python scraper.py`, then `migrate_to_supabase.py`,
`extract_symptoms.py` and `rebuild_rubrics.py` as above.

Tests (no database or network needed): `python test_extract_symptoms.py` and `python test_scraper_parse.py`
