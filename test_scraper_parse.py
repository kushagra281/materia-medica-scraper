"""
Tests for the materiamedica.info parser (no network, no database).

    python test_scraper_parse.py
"""

from bs4 import BeautifulSoup

import scraper


def page(body_html: str, name: str = "ARNICA MONTANA") -> BeautifulSoup:
    # <title> and the navigation repeat the remedy name BEFORE the <h1>, like the real site
    return BeautifulSoup(f"""
    <html><head><title>{name} from Materia Medica by William Boericke. Homeopathy.</title></head>
    <body>
      <nav>Free Materia Medica books <a href="#">Materia Medica</a> by William Boericke
           Index A B C D E F G H I J K L M N O P Q R S T U V W X Y Z 123</nav>
      <h1>{name}</h1>
      {body_html}
      <div>Copyright © 2026 Someone</div>
    </body></html>""", "html.parser")


PLAIN = """
  <p>more information and order at Remedia Homeopathy.</p>
  <p>Leopard's Bane.</p>
  <p>(ARNICA).</p>
  <p>Produces conditions upon the system like injury.</p>
  <p>Mind.-- Fears touch; wants to be left alone.</p>
  <p>Head.-- Hot, with cold body; confused.</p>
  <p>Dose.-- Third potency.</p>
"""

# heading in its own tag: the text lands on the NEXT line when the page is flattened
BOLD = """
  <p>more information and order at Remedia Homeopathy.</p>
  <p>Leopard's Bane.</p>
  <p>(ARNICA).</p>
  <p>Produces conditions upon the system like injury.</p>
  <p><b>Mind.--</b> Fears touch; <i>wants</i> to be left alone.</p>
  <p><strong>Head.--</strong> Hot, with cold body; confused.</p>
"""


def parse(html):
    return scraper.mm_parse("https://www.materiamedica.info/en/materia-medica/william-boericke/arnica-montana", page(html))


def test_plain_layout():
    r = parse(PLAIN)
    assert r.common_name == "Leopard's Bane"
    assert [s.heading for s in r.sections] == ["Mind", "Head", "Dose"]
    assert r.introduction.startswith("(ARNICA).") and "Index A B C" not in r.introduction


def test_heading_in_its_own_tag_is_still_found():
    r = parse(BOLD)
    assert [s.heading for s in r.sections] == ["Mind", "Head"], r.sections
    assert r.sections[0].content == "Fears touch; wants to be left alone."


def test_navigation_and_footer_do_not_leak():
    r = parse(PLAIN)
    text = r.introduction + " ".join(s.content for s in r.sections)
    assert "Copyright" not in text and "Free Materia Medica" not in text and "Remedia" not in text


def test_clean_spacing():
    assert scraper._clean("word , next ( x ) .") == "word, next (x)."


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok  ", name)
    print("all tests passed")
