"""
rebuild_rubrics.py
------------------
Re-derives `rubrics` and `rubric_remedies` from `remedy_symptoms`.

Why: in the live database these two tables are a copy of remedy_symptoms (17,678 depth-2
rubrics for 17,678 symptom rows, every rubric_remedies.source = 'scraped'). When
extract_symptoms.py is re-run, remedy_symptoms changes and the copy goes stale. Run this
afterwards to bring them back in line:

    python extract_symptoms.py
    python rebuild_rubrics.py

What it builds
    depth 1  one rubric per heading (section)            e.g. "Respiratory"
    depth 2  one rubric per distinct (heading, symptom)  e.g. "Respiratory > Cough worse at night"
    rubric_remedies  one row per (rubric, remedy), grade = 1, source = 'scraped'

Grades: the scraped text carries no repertory grades, so every link is grade 1 (the old
copy guessed 2-3 from words like "violent"/"great", which is not a clinical grade).

Refuses to run if saved cases (case_symptoms) point at rubrics, because replacing the
rubrics would break them. Environment: SUPA_HOST, SUPA_USER, SUPA_PASSWORD
(SUPA_PORT, SUPA_DATABASE optional), like extract_symptoms.py.
"""

import os

SQL_DELETE = [
    "DELETE FROM rubric_modalities",
    "DELETE FROM rubric_remedies",
    "DELETE FROM rubrics",
]

SQL_SECTIONS = """
    INSERT INTO rubrics (section, rubric_text, full_path, depth, symptom_type, is_eliminating)
    SELECT heading, heading, heading, 1,
           CASE WHEN lower(heading) ~ '^(mind|mental)' THEN 'mind' ELSE 'particular' END,
           false
    FROM (SELECT DISTINCT heading FROM remedy_symptoms) h
"""

SQL_SYMPTOMS = """
    INSERT INTO rubrics (parent_id, section, rubric_text, full_path, depth, symptom_type, is_eliminating)
    SELECT p.id, d.heading, d.symptom, d.heading || ' > ' || d.symptom, 2,
           CASE WHEN lower(d.heading) ~ '^(mind|mental)' THEN 'mind' ELSE 'particular' END,
           false
    FROM (SELECT DISTINCT heading, symptom FROM remedy_symptoms) d
    JOIN rubrics p ON p.depth = 1 AND p.section = d.heading
"""

SQL_LINKS = """
    INSERT INTO rubric_remedies (rubric_id, remedy_id, remedy_name, grade, source)
    SELECT DISTINCT r.id, s.remedy_id, s.remedy_name, 1, 'scraped'
    FROM remedy_symptoms s
    JOIN rubrics r ON r.depth = 2 AND r.section = s.heading AND r.rubric_text = s.symptom
"""


def run():
    import psycopg2

    conn = psycopg2.connect(
        host=os.environ["SUPA_HOST"],
        port=int(os.environ.get("SUPA_PORT", 5432)),
        dbname=os.environ.get("SUPA_DATABASE", "postgres"),
        user=os.environ["SUPA_USER"],
        password=os.environ["SUPA_PASSWORD"],
    )
    cur = conn.cursor()

    cur.execute("SELECT count(*) FROM case_symptoms WHERE rubric_id IS NOT NULL")
    in_use = cur.fetchone()[0]
    if in_use:
        raise SystemExit(f"Refusing to rebuild: {in_use} saved case symptoms reference rubrics.")

    cur.execute("SELECT count(*) FROM remedy_symptoms")
    if cur.fetchone()[0] == 0:
        raise SystemExit("remedy_symptoms is empty - run extract_symptoms.py first.")

    for sql in SQL_DELETE:
        cur.execute(sql)
    cur.execute(SQL_SECTIONS)
    cur.execute(SQL_SYMPTOMS)
    cur.execute(SQL_LINKS)
    cur.execute("ANALYZE rubrics")
    cur.execute("ANALYZE rubric_remedies")

    cur.execute("SELECT count(*) FROM rubrics")
    n_rub = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM rubric_remedies")
    n_rr = cur.fetchone()[0]
    conn.commit()
    conn.close()
    print(f"Done: {n_rub} rubrics, {n_rr} rubric_remedies")


if __name__ == "__main__":
    run()
