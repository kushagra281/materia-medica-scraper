"""
Tests for extract_symptoms.py helpers (no database needed).

    python test_extract_symptoms.py
"""

from extract_symptoms import split_symptoms, build_rows, name_key, clean_name, wrap_long, KENT_SOURCE


def test_short_symptoms_are_kept():
    out = split_symptoms("Vertigo; nausea. Thirst for cold water. Fear of death. Colic.")
    assert "Vertigo" in out
    assert "nausea" in out
    assert "Colic" in out
    assert "Thirst for cold water" in out


def test_modality_stays_with_complaint():
    out = split_symptoms("Burning pains, worse at night; better, warmth. Fear of death.")
    assert "Burning pains, worse at night; better, warmth" in out
    assert "better, warmth" not in out          # not a stand-alone row any more
    assert "Fear of death" in out


def test_junk_and_references_are_skipped():
    out = split_symptoms("(Ars; Plat). See. Also. Real symptom here.")
    assert out == ["Real symptom here"]


def test_semicolons_inside_parentheses_do_not_split():
    out = split_symptoms("Anxiety (compare Ars.; Plat.) at night; worse, cold.")
    assert out == ["Anxiety (compare Ars.; Plat.) at night; worse, cold"]


def test_name_canonicalisation():
    assert clean_name("  ARSENICUM   ALBUM. ") == "ARSENICUM ALBUM"
    assert name_key("ARSENICUM ALBUM.") == name_key("Arsenicum  album") == "arsenicum album"


def test_same_sentence_from_two_sites_is_stored_once():
    sections = [
        {"remedy_id": 1, "remedy_name": "ARSENICUM ALBUM", "heading": "Mind", "content": "Anxious, restless. Fear of death."},
        {"remedy_id": 2, "remedy_name": "Arsenicum Album.", "heading": "Mind", "content": "Anxious, restless. Fear of death."},
        {"remedy_id": 3, "remedy_name": "BELLADONNA", "heading": "Dose", "content": "Third potency."},
    ]
    rows, stats = build_rows(sections)
    symptoms = [r[3] for r in rows]
    assert symptoms.count("Anxious, restless") == 1
    assert {r[1] for r in rows} == {"ARSENICUM ALBUM"}          # one canonical spelling
    assert stats["duplicates_removed"] == 2
    assert "Dose" in stats["skipped_headings"]


def test_kent_names_are_merged_onto_boericke_spelling():
    sections = [
        {"remedy_id": 1, "remedy_name": "BRYONIA ALBA", "source_site": "materiamedica.info", "heading": "Head", "content": "Headache worse motion."},
        {"remedy_id": 2, "remedy_name": "BRYONIA", "source_site": KENT_SOURCE, "heading": "Kent Lectures", "content": "The patient is worse from motion. Wants to lie still."},
        {"remedy_id": 3, "remedy_name": "KALI BICHROMICUM", "source_site": KENT_SOURCE, "heading": "Kent Lectures", "content": "Ropy discharges."},
        {"remedy_id": 4, "remedy_name": "KALIUM BICHROMICUM", "source_site": "materiamedica.info", "heading": "Nose", "content": "Ropy mucus."},
        {"remedy_id": 5, "remedy_name": "AURUM MURIATICUM", "source_site": KENT_SOURCE, "heading": "Kent Lectures", "content": "Heart symptoms."},
        {"remedy_id": 6, "remedy_name": "AURUM MURIATICUM NATRONATUM", "source_site": "materiamedica.info", "heading": "Mind", "content": "Depressed."},
    ]
    rows, stats = build_rows(sections)
    names = {r[1] for r in rows}
    assert "BRYONIA" not in names and "BRYONIA ALBA" in names           # merged
    assert "KALI BICHROMICUM" not in names and "KALIUM BICHROMICUM" in names
    assert "AURUM MURIATICUM" in names and "AURUM MURIATICUM NATRONATUM" in names   # NOT merged (different substances)
    kent_rows = [r for r in rows if r[5] == "kent"]
    assert len(kent_rows) == 4 and all(r[2] == "Kent Lectures" for r in kent_rows[:3])


def test_title_clutter_is_removed_from_names():
    assert clean_name("GLONOINUM : GL = Glycerin; O = Oxygen; N = Nitrogen") == "GLONOINUM"
    assert clean_name("ABRUS PRECATORIUS -- JEQUIRITY") == "ABRUS PRECATORIUS"
    assert clean_name("ABIES CANADENSIS-PINUS CANADENSIS") == "ABIES CANADENSIS-PINUS CANADENSIS"


def test_long_sentences_are_cut_at_a_comma():
    long = ", ".join(["the patient is worse from motion"] * 40)
    parts = wrap_long(long)
    assert len(parts) > 1 and all(len(p) <= 500 for p in parts)
    assert " ".join(parts).replace(",", "").split() == long.replace(",", "").split()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok  ", name)
    print("all tests passed")
