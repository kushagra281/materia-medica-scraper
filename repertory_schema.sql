-- ================================================================
--  Graded repertories (rubric tree + remedy grades)
--
--  Safe to run any number of times (CREATE ... IF NOT EXISTS). It never touches the
--  existing `rubrics` / `rubric_remedies` tables, which are derived from remedy_symptoms
--  and carry no real grades. import_repertory.py runs this file before loading.
--
--  Removing a book again (e.g. if its licence does not suit you) is one statement:
--      DELETE FROM repertory_sources WHERE slug = 'repertorium-publicum-2008';
--  The ON DELETE CASCADE below removes its rubrics and remedies with it.
-- ================================================================

CREATE TABLE IF NOT EXISTS repertory_sources (
    slug         TEXT        PRIMARY KEY,
    title        TEXT        NOT NULL,
    author       TEXT        NOT NULL,
    year         INT,
    licence      TEXT        NOT NULL,          -- e.g. "GNU GPL v3"
    source_url   TEXT        NOT NULL DEFAULT '',
    attribution  TEXT        NOT NULL,          -- shown to the user wherever the data is used
    note         TEXT        NOT NULL DEFAULT '',
    graded       BOOLEAN     NOT NULL DEFAULT TRUE,
    id_base      BIGINT      NOT NULL UNIQUE,   -- rubric ids of this book are id_base + the book's own number
    rubric_count INT         NOT NULL DEFAULT 0,
    link_count   INT         NOT NULL DEFAULT 0,
    imported_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Remedy abbreviation as printed in the book -> remedy name.
CREATE TABLE IF NOT EXISTS repertory_remedies (
    source     TEXT NOT NULL REFERENCES repertory_sources(slug) ON DELETE CASCADE,
    abbrev     TEXT NOT NULL,
    name       TEXT NOT NULL,
    link_count INT  NOT NULL DEFAULT 0,
    PRIMARY KEY (source, abbrev)
);

-- One row per rubric. The remedies of a rubric are packed into one jsonb object
-- {"Acon.": 3, "Bell.": 2, ...} (abbreviation -> grade 1..3), so a search reads a few dozen
-- rows instead of paging through hundreds of thousands of link rows.
CREATE TABLE IF NOT EXISTS repertory_rubrics (
    id           BIGINT   PRIMARY KEY,
    source       TEXT     NOT NULL REFERENCES repertory_sources(slug) ON DELETE CASCADE,
    parent_id    BIGINT,                         -- NULL = a chapter
    chapter      TEXT     NOT NULL,              -- text of the chapter (root) this rubric sits in
    rubric_text  TEXT     NOT NULL,              -- this rubric's own words, e.g. "night"
    full_path    TEXT     NOT NULL,              -- "Mind > anxiety > night"
    depth        SMALLINT NOT NULL,              -- 0 = chapter
    n_remedies   INT      NOT NULL,
    child_count  INT      NOT NULL DEFAULT 0,
    remedies     JSONB    NOT NULL
);

CREATE INDEX IF NOT EXISTS repertory_rubrics_parent_idx ON repertory_rubrics (parent_id);
CREATE INDEX IF NOT EXISTS repertory_rubrics_source_idx ON repertory_rubrics (source);

-- Read-only for the app (same pattern as the other tables here); writes need the database password.
ALTER TABLE repertory_sources  ENABLE ROW LEVEL SECURITY;
ALTER TABLE repertory_remedies ENABLE ROW LEVEL SECURITY;
ALTER TABLE repertory_rubrics  ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public read repertory_sources"  ON repertory_sources;
DROP POLICY IF EXISTS "Public read repertory_remedies" ON repertory_remedies;
DROP POLICY IF EXISTS "Public read repertory_rubrics"  ON repertory_rubrics;
CREATE POLICY "Public read repertory_sources"  ON repertory_sources  FOR SELECT USING (true);
CREATE POLICY "Public read repertory_remedies" ON repertory_remedies FOR SELECT USING (true);
CREATE POLICY "Public read repertory_rubrics"  ON repertory_rubrics  FOR SELECT USING (true);
