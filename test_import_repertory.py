"""
Tests for import_repertory.py (no database, no network).

    python test_import_repertory.py
"""

import json
import os
import tempfile

import import_repertory as ir

SLUG = "repertorium-publicum-2008"
BASE = ir.BOOKS[SLUG]["id_base"]


def rub(n, text, parent=None, remedies=()):
    return {
        "id": f"{SLUG}-r{n:05d}",
        "text": text,
        "parent": f"{SLUG}-r{parent:05d}" if parent else None,
        "remedies": [{"abbrev": a, "grade": g, "polarity": "+", "name": nm} for a, g, nm in remedies],
    }


def write_book(folder_files):
    """folder_files: {filename: [rubric dicts]} -> data dir with repertory/<slug>/<file>."""
    root = tempfile.mkdtemp()
    book = os.path.join(root, "repertory", SLUG)
    os.makedirs(book)
    for name, rubrics in folder_files.items():
        with open(os.path.join(book, name), "w", encoding="utf-8") as fh:
            json.dump({"type": "repertory", "book": {"id": SLUG},
                       "section": {"id": "s", "title": name, "rubrics": rubrics}}, fh)
    return root


SAMPLE = {
    "mind.json": [
        rub(1, "Mind", None, [("Acon.", 3, "Aconitum napellus"), ("Bell.", 1, "Belladonna")]),
        rub(2, "anxiety", 1, [("Acon.", 3, "Aconitum napellus"), ("Ars.", 2, "Arsenicum album")]),
        rub(3, "night", 2, [("Ars.", 3, "Arsenicum album")]),
    ],
    # a rubric whose parent lives in another file
    "head.json": [
        rub(4, "Head", None, [("Bell.", 3, "Belladonna")]),
        rub(5, "pain", 4, [("Bell.", 2, "Belladonna"), ("Acon.", 1, "Aconitum napellus")]),
        rub(6, "throbbing", 5, [("Bell.", 3, "Belladonna")]),
    ],
}


def built(files=SAMPLE):
    data_dir = write_book(files)
    return ir.build(SLUG, ir.load_records(data_dir, SLUG))


def test_tree_paths_chapters_and_depth():
    rows, _, stats = built()
    by_id = {r[0]: r for r in rows}
    night = by_id[BASE + 3]
    assert night[3] == "Mind"                    # chapter
    assert night[4] == "night"                   # own text
    assert night[5] == "Mind > anxiety > night"  # full path
    assert night[6] == 2                         # depth
    assert night[2] == BASE + 2                  # parent id
    assert by_id[BASE + 1][2] is None            # chapter has no parent
    assert stats["chapters"] == 2 and stats["max_depth"] == 2 and stats["rubrics"] == 6


def test_child_count_and_remedy_counts():
    rows, remedies, stats = built()
    by_id = {r[0]: r for r in rows}
    assert by_id[BASE + 1][8] == 1 and by_id[BASE + 3][8] == 0
    assert by_id[BASE + 2][7] == 2               # n_remedies
    assert by_id[BASE + 2][9] == {"Acon.": 3, "Ars.": 2}
    assert stats["links"] == 2 + 2 + 1 + 1 + 2 + 1
    names = {r[1]: (r[2], r[3]) for r in remedies}
    assert names["Acon."] == ("Aconitum napellus", 3)        # appears in 3 rubrics
    assert names["Bell."][1] == 4                            # rubrics 1, 4, 5, 6


def test_parent_in_another_file_is_resolved():
    rows, _, stats = built()
    by_id = {r[0]: r for r in rows}
    assert by_id[BASE + 6][5] == "Head > pain > throbbing"
    assert by_id[BASE + 6][3] == "Head"
    assert stats["problems"] == {}


def test_duplicate_remedy_keeps_highest_grade_and_is_reported():
    rows, _, stats = built({"a.json": [
        rub(1, "Mind", None, [("Acon.", 1, "Aconitum"), ("Acon.", 3, "Aconitum")]),
    ]})
    assert rows[0][9] == {"Acon.": 3}
    assert any("twice" in k for k in stats["notes"]) and stats["problems"] == {}


def test_links_without_a_real_grade_are_skipped_and_reported():
    rows, remedies, stats = built({"a.json": [
        rub(1, "Mind", None, [("Acon.", None, "Aconitum"), ("Bell.", 4, "Belladonna"),
                              ("Ars.", True, "Arsenicum"), ("Calc.", 2, "Calcarea")]),
    ]})
    assert rows[0][9] == {"Calc.": 2}
    assert [r[1] for r in remedies] == ["Calc."]
    assert any("grade 1-3" in k for k in stats["problems"])


def test_missing_parent_becomes_a_chapter_and_is_reported():
    rows, _, stats = built({"a.json": [rub(7, "orphan", 99, [("Acon.", 2, "Aconitum")])]})
    assert rows[0][2] is None and rows[0][3] == "orphan" and rows[0][6] == 0
    assert any("parent not found" in k for k in stats["problems"])


def test_loop_is_cut_not_followed_forever():
    rows, _, stats = built({"a.json": [
        rub(1, "a", 2, [("Acon.", 1, "Aconitum")]),
        rub(2, "b", 1, [("Acon.", 1, "Aconitum")]),
    ]})
    assert len(rows) == 2 and any("loop" in k for k in stats["problems"])


def test_nul_and_whitespace_are_cleaned():
    rows, _, _ = built({"a.json": [rub(1, "  Mi\x00nd \n  fear ", None, [("Acon.", 1, "Aconitum")])]})
    assert rows[0][4] == "Mi nd fear" and "\x00" not in rows[0][5]


def test_abbreviation_with_two_names_keeps_the_most_common():
    _, remedies, stats = built({"a.json": [
        rub(1, "x", None, [("Sil.", 1, "Silicea")]),
        rub(2, "y", None, [("Sil.", 1, "Silicea")]),
        rub(3, "z", None, [("Sil.", 1, "Silica")]),
    ]})
    assert remedies[0][2] == "Silicea"
    assert any("more than one name" in k for k in stats["notes"]) and stats["problems"] == {}


def test_duplicate_rubric_id_is_reported():
    _, _, stats = built({"a.json": [rub(1, "x"), rub(1, "again")]})
    assert any("duplicate" in k for k in stats["problems"])


def test_dry_run_needs_no_database_and_loads_nothing(capsys=None):
    data_dir = write_book(SAMPLE)
    saved = {k: os.environ.pop(k, None) for k in ("PGHOST", "SUPA_HOST")}
    try:
        assert ir.main(["--data-dir", data_dir, "--book", SLUG, "--dry-run"]) == 0
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_data_with_problems_is_not_loaded_without_permission():
    data_dir = write_book({"a.json": [rub(1, "x", 99, [("Acon.", 1, "Aconitum")])]})
    assert ir.main(["--data-dir", data_dir, "--book", SLUG]) == 1


def test_only_listed_books_are_accepted():
    try:
        ir.main(["--data-dir", ".", "--book", "kent-1897", "--dry-run"])
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("an unlisted book was accepted")


def test_schema_file_is_safe_to_rerun_and_read_only_for_the_app():
    here = os.path.dirname(os.path.abspath(__file__))
    sql = open(os.path.join(here, "repertory_schema.sql"), encoding="utf-8").read().upper()
    assert "DROP TABLE" not in sql
    assert sql.count("CREATE TABLE") == sql.count("CREATE TABLE IF NOT EXISTS") == 3
    assert "ON DELETE CASCADE" in sql
    for t in ("REPERTORY_SOURCES", "REPERTORY_REMEDIES", "REPERTORY_RUBRICS"):
        assert f"ALTER TABLE {t}" in sql and "ENABLE ROW LEVEL SECURITY" in sql
    assert " FOR INSERT" not in sql and " FOR UPDATE" not in sql and " FOR ALL" not in sql


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok  ", name)
    print("all tests passed")
