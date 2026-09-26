"""Loads the learning content (scenarios, lessons, word lists) from JSON once at startup."""
import json
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

def _load(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


class Content:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.scenario_list = _load(data_dir / "papiamentuPaBoScenarios.json")
        self.scenarios = {
            p.stem: _load(p) for p in sorted((data_dir / "scenarios").glob("scenario-*.json"))
        }
        lessen = [_load(p) for p in sorted((data_dir / "lessen").glob("les-*.json"))]
        self.lessen = sorted((l for l in lessen if l.get("id") is not None), key=lambda l: l["id"])
        self.lessen_by_id = {l["id"]: l for l in self.lessen}
        self.woordenlijsten = _load(data_dir / "woordenlijsten.json")["lijsten"]
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
