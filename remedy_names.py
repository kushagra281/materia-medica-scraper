"""
remedy_names.py
---------------
One place that decides what a remedy is called, so the same remedy from two books
(Boericke, Kent) is counted once by the app.

* clean_remedy_name()   removes site clutter from a title, e.g.
      "GLONOINUM : GL = Glycerin; O = Oxygen; N = Nitrogen" -> "GLONOINUM"
      "ABRUS PRECATORIUS -- JEQUIRITY"                       -> "ABRUS PRECATORIUS"
* name_key()            case/punctuation-insensitive key
* canonical_name()      maps a Kent title to the Boericke spelling when it is certainly the
                        same remedy (reviewed list + safe spelling rules). Anything uncertain
                        is NOT merged: two entries for one remedy are better than one wrong
                        merge (e.g. Aurum muriaticum is not Aurum muriaticum natronatum).
"""

import re


def clean_remedy_name(name: str) -> str:
    n = re.sub(r"\s+", " ", name or "").strip()
    n = re.split(r"\s*:\s+|\s+--\s+", n)[0]          # drop " : explanation" and " -- vernacular name"
    return n.rstrip(".,;:").strip()


def name_key(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", clean_remedy_name(name).lower())).strip()


# Spelling differences between Kent's titles and Boericke's (old vs new Latin names).
_WORD_MAP = {
    "kali": "kalium", "natrum": "natrium", "magnesia": "magnesium",
    "silica": "silicea", "cinchona": "china", "iodine": "iodium", "camphor": "camphora",
}


def _kent_key(name: str) -> str:
    k = name_key(re.sub(r"\(.*?\)", " ", name))
    k = re.sub(r"\b([a-z]+)ic acid\b", r"\1icum acidum", k)        # nitric acid -> nitricum acidum
    return " ".join(_WORD_MAP.get(w, w) for w in k.split())


# Reviewed: Kent title (as _kent_key gives it) -> Boericke title. Only same-substance pairs.
KENT_ALIASES = {
    "asafoetida": "ASA FOETIDA",
    "baptisia": "BAPTISIA TINCTORIA",
    "berberis": "BERBERIS VULGARIS",
    "guaiacum": "GUAJACUM OFFICINALE",
    "magnesium carbonica": "MAGNESIUM CARBONICUM",
    "magnesium muriatica": "MAGNESIUM MURIATICUM",
    "magnesium phosphorica": "MAGNESIUM PHOSPHORICUM",
    "borax": "BORAX VENETA",
    "bryonia": "BRYONIA ALBA",
    "bufo": "BUFO RANA",
    "caladium": "CALADIUM SEGUINUM",
    "cantharis": "CANTHARIS VESICATORIA",
    "capsicum": "CAPSICUM ANNUUM",
    "chelidonium": "CHELIDONIUM MAJUS",
    "china": "CHINA OFFICINALIS",
    "digitalis": "DIGITALIS PURPUREA",
    "euphrasia": "EUPHRASIA OFFICINALIS",
    "gelsemium": "GELSEMIUM SEMPERVIRENS",
    "hyoscyamus": "HYOSCYAMUS NIGER",
    "hypericum": "HYPERICUM PERFORATUM",
    "ignatia": "IGNATIA AMARA",
    "lachesis": "LACHESIS MUTUS",
    "lycopodium": "LYCOPODIUM CLAVATUM",
    "manganum": "MANGANUM ACETICUM",
    "naja": "NAJA TRIPUDIANS",
    "phytolacca": "PHYTOLACCA DECANDRA",
    "platinum": "PLATINUM METALLICUM",
    "podophyllum": "PODOPHYLLINUM",
    "pulsatilla": "PULSATILLA PRATENSIS",
    "ruta graveole s": "RUTA GRAVEOLENS",
    "ruta graveolens": "RUTA GRAVEOLENS",
    "sanguinaria": "SANGUINARIA CANADENSIS",
    "sarsaparilla": "SARSAPARILLA OFFICINALIS",
    "selenium": "SELENIUM METALLICUM",
    "sepia": "SEPIA OFFICINALIS",
    "silicea": "SILICEA TERRA",
    "spigelia anthelmintica": "SPIGELIA ANTHELMIA",
    "squilla": "SQUILLA MARITIMA",
    "staphisagria": "STAPHYSAGRIA",
    "theridion": "THERIDION CURASSAVICUM",
    "tuberculinum bovinum": "TUBERCULINUM",
    "valerian": "VALERIANA OFFICINALIS",
    "dulcamara": "DULCAMARA",
    "eupatorium perfoliatum": "EUPATORIUM PERFOLIATUM",
    "crotalus horridus": "CROTALUS HORRIDUS",
    "actaea racemosa": "ACTAEA RACEMOSA",
}


def canonical_name(name: str, known: set[str] | None = None) -> str:
    """
    Canonical spelling for a remedy title.

    known = name_keys of remedies that exist (from Boericke). A Kent title is mapped to the
    Boericke spelling when (a) the normalised names are equal, or (b) it is in KENT_ALIASES
    and that Boericke remedy exists. Otherwise the cleaned title is kept as it is.
    Trailing vernacular words ("... Bitter Sweet") are tried off one at a time.
    """
    cleaned = clean_remedy_name(name)
    known = known or set()
    words = _kent_key(cleaned).split()
    while words:
        key = " ".join(words)
        for cand in (key, KENT_ALIASES.get(key)):
            if cand and name_key(cand) in known:
                return clean_remedy_name(cand) if cand != key else cand.upper()
        words = words[:-1]                       # drop one trailing word and retry
    return cleaned.upper()
