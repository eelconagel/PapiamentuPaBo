"""Loads the learning content (scenarios, lessons, word lists) from JSON once at startup."""
import json
import re
import unicodedata
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

NIVEAU_LABEL = {
    "Easy": "Eenvoudig",
    "Intermediate": "Gemiddeld",
    "Hard": "Moeilijk",
    "Native Speaker": "Expert",
}

NIVEAU_COLOR = {
    "Easy": "var(--fill-green)",
    "Intermediate": "var(--fill-orange)",
    "Hard": "var(--fill-red)",
    "Native Speaker": "var(--fill-purple)",
}

# News categories are in Papiamentu (like the rubrieken of a local paper), with a Dutch gloss.
KATEGORIA_NL = {
    "Lokal": "Lokaal",
    "Ekonomia": "Economie",
    "Deporte": "Sport",
    "Farándula": "Uitgaan & showbizz",
    "Kultura": "Cultuur",
    "Tempu": "Weer",
    "Salú": "Gezondheid",
    "Enseñansa": "Onderwijs",
    "Naturalesa": "Natuur",
    "Boneiru": "Bonaire",
    "Aruba": "Aruba",
}


# News articles unlock gradually (in file order): the first OPEN are available right away, and
# every PER articles read frees the next PER. Progress lives in the browser, so the check is in JS.
NIEUWS_UNLOCK = {"open": 8, "per": 3}


def _load(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _slug(text: str) -> str:
    """ASCII-only, hyphenated slug — used to build word ids for scenarios/nieuws/lessen,
    which (unlike woordenlijsten.json) have no id of their own per word."""
    ascii_text = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return slug[:40] or "x"


class Content:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.scenario_list = _load(data_dir / "papiamentuPaBoScenarios.json")
        self.scenarios = {
            p.stem: _load(p) for p in sorted((data_dir / "scenarios").glob("scenario-*.json"))
        }
        lessen = [_load(p) for p in sorted((data_dir / "lessen").glob("les-*.json"))]
        self.lessen = sorted((l for l in lessen if l.get("id") is not None), key=lambda l: l["id"])
        self.lessen_by_id = {l["id"]: l for l in self.lessen}
        # Reading practice: short news articles, keyed by id ("nieuws-001"), in file order.
        self.nieuws = {
            a["id"]: a for a in (_load(p) for p in sorted((data_dir / "nieuws").glob("nieuws-*.json")))
        }
        self.woordenlijsten = _load(data_dir / "woordenlijsten.json")["lijsten"]
        # Vaste naslag-lijst met de nuttigste zinnen, buiten de lessenvolgorde om — voor
        # iemand die zich geen 40 lessen kan permitteren voor het vliegtuig vertrekt.
        self.noodwoordenboek = _load(data_dir / "noodwoordenboek.json")["categorieen"]
        # Flat list used for the word of the day, in the same order as the app.
        self._all_words = [
            {"word": w["woord"], "pronunciation": w["uitspraak"], "translation": w["vertaling"]}
            for lijst in self.woordenlijsten
            for w in lijst["woorden"]
        ]

    def all_words(self):
        return self._all_words

    def scenario_title(self, scenario_id: str) -> str:
        s = self.scenarios.get(scenario_id)
        return s["title"] if s else scenario_id

    def alle_leerwoorden(self):
        """One flat, deduplicated-by-id list of every word taught anywhere on the site:
        the fixed woordenlijsten (own id, e.g. "w1_01") plus the vocabulary sections of
        lessen, scenario's and nieuws (id built from the source + a slug, since those don't
        carry their own word ids). "bron" tells the front end which lesson/scenario/article
        a word came from, so it can only be practised once that content has been seen —
        see Store.medailleVoortgang-achtige gating in woorden.html.
        """
        out = []
        seen_ids = set()

        def add(bron, woord, uitspraak, vertaling):
            base = f"{bron}:{_slug(woord)}"
            wid, n = base, 2
            while wid in seen_ids:
                wid = f"{base}-{n}"
                n += 1
            seen_ids.add(wid)
            out.append({"id": wid, "woord": woord, "uitspraak": uitspraak, "vertaling": vertaling, "bron": bron})

        for lijst in self.woordenlijsten:
            for w in lijst["woorden"]:
                seen_ids.add(w["id"])
                out.append({"id": w["id"], "woord": w["woord"], "uitspraak": w["uitspraak"],
                           "vertaling": w["vertaling"], "bron": f"woordenlijst-{lijst['id']}"})
        for les in self.lessen:
            for w in les.get("woorden", []):
                add(f"les-{les['id']}", w["woord"], w["uitspraak"], w["vertaling"])
        for sid, s in self.scenarios.items():
            for w in s.get("words", []):
                add(sid, w["papiamentu"], w["pronunciation"], w["dutch"])
        for aid, a in self.nieuws.items():
            for w in a.get("sleutelwoorden", []):
                add(aid, w["woord"], w["uitspraak"], w["vertaling"])
        return out
