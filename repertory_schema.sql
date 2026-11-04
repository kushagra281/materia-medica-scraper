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

-- ── Remedy -> rubrics ("which rubrics contain Sulph. and Calc., but not Puls.?") ──────────────
-- The GIN index makes the jsonb key tests (?& all of, ?| any of) fast on 74k rubrics.
CREATE INDEX IF NOT EXISTS repertory_rubrics_remedies_gin ON repertory_rubrics USING gin (remedies);

-- Narrowest rubrics first: a rubric holding few remedies says more about them than a huge one.
-- Every included remedy must be at p_min_grade or higher; no excluded remedy may be present.
CREATE OR REPLACE FUNCTION repertory_rubrics_by_remedies(
    p_source    TEXT,
    p_include   TEXT[],
    p_exclude   TEXT[] DEFAULT '{}',
    p_min_grade INT    DEFAULT 1,
    p_limit     INT    DEFAULT 100,
    p_offset    INT    DEFAULT 0
) RETURNS TABLE (
    id BIGINT, chapter TEXT, full_path TEXT, depth SMALLINT,
    n_remedies INT, child_count INT, grades JSONB
)
LANGUAGE sql STABLE SET search_path = public AS $$
    SELECT r.id, r.chapter, r.full_path, r.depth, r.n_remedies, r.child_count,
           (SELECT jsonb_object_agg(k, r.remedies -> k) FROM unnest(p_include) AS k) AS grades
      FROM repertory_rubrics r
     WHERE cardinality(p_include) BETWEEN 1 AND 5
       AND cardinality(p_exclude) <= 50
       AND r.source = p_source
       AND r.depth > 0
       AND r.remedies ?& p_include
       AND NOT (r.remedies ?| p_exclude)
       AND (SELECT bool_and((r.remedies ->> k)::int >= p_min_grade) FROM unnest(p_include) AS k)
     ORDER BY r.n_remedies ASC, r.id ASC
     LIMIT least(greatest(p_limit, 1), 200) OFFSET greatest(p_offset, 0)
$$;

GRANT EXECUTE ON FUNCTION repertory_rubrics_by_remedies(TEXT, TEXT[], TEXT[], INT, INT, INT) TO anon, authenticated;
