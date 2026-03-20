-- ================================================================
--  Homeopathic Materia Medica — PostgreSQL Schema
--  Source: William Boericke's Materia Medica (1901)
--  Sites : materiamedica.info | homeoint.org
-- ================================================================

-- Drop in safe order (children before parents)
DROP TABLE IF EXISTS remedy_sections CASCADE;
DROP TABLE IF EXISTS remedies         CASCADE;
DROP TABLE IF EXISTS scrape_log       CASCADE;

-- ────────────────────────────────────────────────────────────────
-- 1.  remedies
--     One row per remedy, deduplicated by slug.
--     slug is the URL path segment, e.g. "arsenicum-album".
-- ────────────────────────────────────────────────────────────────
CREATE TABLE remedies (
    id           SERIAL       PRIMARY KEY,
    slug         TEXT         NOT NULL UNIQUE,
    name         TEXT         NOT NULL,         -- e.g. "ARSENICUM ALBUM"
    common_name  TEXT         NOT NULL DEFAULT '', -- e.g. "Arsenious Acid"
    introduction TEXT         NOT NULL DEFAULT '', -- text before first section
    source_site  TEXT         NOT NULL,         -- "materiamedica.info" | "homeoint.org"
    source_url   TEXT         NOT NULL UNIQUE,
    total_chars  INT          NOT NULL DEFAULT 0, -- intro + all section chars
    section_count INT         NOT NULL DEFAULT 0,
    scraped_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ────────────────────────────────────────────────────────────────
-- 2.  remedy_sections
--     One row per section per remedy.
--     heading is the exact word Boericke used, e.g. "Mind", "Head".
--     heading_order preserves the document sequence.
-- ────────────────────────────────────────────────────────────────
CREATE TABLE remedy_sections (
    id            SERIAL  PRIMARY KEY,
    remedy_id     INT     NOT NULL REFERENCES remedies(id) ON DELETE CASCADE,
    heading       TEXT    NOT NULL,
    heading_order SMALLINT NOT NULL,
    content       TEXT    NOT NULL,
    char_count    INT     NOT NULL DEFAULT 0,
    UNIQUE (remedy_id, heading)        -- one row per heading per remedy
);

-- ────────────────────────────────────────────────────────────────
-- 3.  scrape_log
--     Full audit trail — every URL attempted is recorded here.
-- ────────────────────────────────────────────────────────────────
CREATE TABLE scrape_log (
    id        SERIAL      PRIMARY KEY,
    url       TEXT        NOT NULL,
    status    TEXT        NOT NULL,   -- "success" | "skip" | "error"
    message   TEXT        NOT NULL DEFAULT '',
    logged_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ────────────────────────────────────────────────────────────────
-- Indexes
-- ────────────────────────────────────────────────────────────────
CREATE INDEX idx_rem_slug         ON remedies (slug);
CREATE INDEX idx_rem_source       ON remedies (source_site);
CREATE INDEX idx_rem_name_fts     ON remedies
    USING GIN (to_tsvector('english', name));

CREATE INDEX idx_sec_remedy_id    ON remedy_sections (remedy_id);
CREATE INDEX idx_sec_heading      ON remedy_sections (heading);
CREATE INDEX idx_sec_content_fts  ON remedy_sections
    USING GIN (to_tsvector('english', content));

-- ────────────────────────────────────────────────────────────────
-- Useful view: full remedy detail in one query
-- ────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_remedy_full AS
SELECT
    r.id           AS remedy_id,
    r.slug,
    r.name,
    r.common_name,
    r.introduction,
    r.source_site,
    r.source_url,
    r.total_chars,
    r.section_count,
    r.scraped_at,
    s.heading,
    s.heading_order,
    s.content,
    s.char_count   AS section_chars
FROM remedies r
LEFT JOIN remedy_sections s ON s.remedy_id = r.id
ORDER BY r.name, s.heading_order;

-- ────────────────────────────────────────────────────────────────
-- Useful view: summary statistics per remedy
-- ────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_remedy_summary AS
SELECT
    r.id,
    r.slug,
    r.name,
    r.common_name,
    r.source_site,
    r.section_count,
    r.total_chars,
    r.scraped_at
FROM remedies r
ORDER BY r.name;
