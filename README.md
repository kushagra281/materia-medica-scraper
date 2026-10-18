# materia-medica-scraper

Scrapes Boericke's Materia Medica and builds the tables the HomeoCare app searches.

## Sources
- William Boericke, *Materia Medica* (1901) - materiamedica.info, labelled sections (Mind, Head, ...)
- James Tyler Kent, *Lectures on Homoeopathic Materia Medica* - materiamedica.info, 95 remedies as
  lecture prose (stored as one "Kent Lectures" section per remedy). Kent names are mapped onto the
  Boericke spelling only when it is certainly the same remedy (`remedy_names.py`); `remedy_symptoms.source`
  says which book a line came from.
- homeoint.org is off by default (`SCRAPE_HOMEOINT=1` to enable).

## How to run (no Railway needed)

**GitHub Actions (recommended).** In this repo: *Settings -> Secrets and variables -> Actions*, add
`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` from Supabase (*Connect -> Session pooler*).
Then *Actions -> Rebuild data -> Run workflow*. It runs the tests, scrapes, extracts symptoms and
rebuilds rubrics, and prints the scrape errors at the end. Takes about 30-60 minutes.

**On your own computer.** `pip install -r requirements.txt`, set the same values as environment
variables (`PGHOST` ... and `SUPA_HOST`, `SUPA_PORT`, `SUPA_DATABASE`, `SUPA_USER`, `SUPA_PASSWORD`),
then `python scraper.py`, `python extract_symptoms.py`, `python rebuild_rubrics.py`.

`schema.sql` is only for an empty database: it **drops** the tables first. Never run it on the live one.
`migrate_to_supabase.py` is only for copying from a separate local Postgres; with the settings above
the scraper writes straight into Supabase and it is not needed.

## One-time repair of the existing data

The first scrape had three problems (found by checking the live database):

- `common_name` is "Materia Medica" for all 476 remedies and every introduction starts with the
  site's navigation - the parser looked for the remedy name in the page `<title>` instead of the `<h1>`.
- 144 of the 620 remedy pages were never saved ("no sections extracted"), e.g. Arnica montana -
  most likely because their section labels sit in their own tag and the label regex needed text on
  the same line. This is fixed in the parser and covered by tests, but **I could not reach the live
  site from my environment, so please check the log after the run** (`scrape_log`, status `error`).
- `remedy_sections.char_count` was never copied by the migration (all 0).

To repair: run the *Rebuild data* workflow with "Re-scrape" ticked (it sets `FORCE_REFRESH=1`).

Tests (no database or network needed): `python test_extract_symptoms.py` and `python test_scraper_parse.py`
