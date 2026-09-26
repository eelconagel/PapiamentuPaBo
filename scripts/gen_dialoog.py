"""Turn a compact dialogue-tree text format into a scenario's "dialoog" field.

Usage: python scripts/gen_dialoog.py <source.txt> [more.txt ...]
Reads/writes papiamentu/data/scenarios/<scenario-id>.json in place: adds or replaces
that scenario's "dialoog" key, leaving every other field untouched.

Compact format (one or more scenario's per source file):

=== scenario-005
KNOOP start
NPC <wat de NPC in het Papiamentu zegt>
NPC_NL <Nederlandse vertaling van die NPC-zin>
KEUZE <Papiamentu keuze> | <Nederlandse vertaling> | <knoop-id waar dit heen leidt>
KEUZE <...> | <...> | <...> | <optionele feedback als dit geen ideale keuze is>

KNOOP <volgende knoop-id>
NPC ...
...

Het eerste KNOOP-blok na een "===" is de startknoop. Een knoop zonder KEUZE-regels is
automatisch een eindpunt van het gesprek (geen "foute" eindes — hooguit een gemiste kans,
via de optionele feedback op een KEUZE). Elke "gaat_naar" moet naar een knoop-id verwijzen
dat ook echt met KNOOP is gedefinieerd (de test hieronder controleert dat).
"""
import json
import sys
from pathlib import Path

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "papiamentu" / "data" / "scenarios"


def parse(text):
    scenarios = {}
    scenario_id = None
    knopen = None
    start = None
    knoop_id = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tag, _, rest = line.partition(" ")
        rest = rest.strip()
        if tag == "===":
            scenario_id = rest
            knopen = {}
            start = None
            knoop_id = None
            scenarios[scenario_id] = {"start": None, "knopen": knopen}
        elif tag == "KNOOP":
            knoop_id = rest
            knopen[knoop_id] = {"npc": "", "npc_nl": "", "keuzes": []}
            if start is None:
                start = knoop_id
                scenarios[scenario_id]["start"] = start
        elif tag == "NPC":
            knopen[knoop_id]["npc"] = rest
        elif tag == "NPC_NL":
            knopen[knoop_id]["npc_nl"] = rest
        elif tag == "KEUZE":
            parts = [p.strip() for p in rest.split("|")]
            pap, nl, gaat_naar = parts[0], parts[1], parts[2]
            keuze = {"pap": pap, "nl": nl, "gaat_naar": gaat_naar}
            if len(parts) > 3 and parts[3]:
                keuze["feedback"] = parts[3]
            knopen[knoop_id]["keuzes"].append(keuze)
        else:
            raise ValueError(f"onbekende regel: {raw!r}")

    # Sanity check: elke gaat_naar moet een bestaande knoop zijn, elke knoop een npc-tekst.
    for sid, d in scenarios.items():
        for kid, k in d["knopen"].items():
            assert k["npc"].strip() and k["npc_nl"].strip(), f"{sid}:{kid} mist NPC/NPC_NL"
            for keuze in k["keuzes"]:
                assert keuze["gaat_naar"] in d["knopen"], f"{sid}:{kid} -> onbekende knoop {keuze['gaat_naar']!r}"
    return scenarios


if __name__ == "__main__":
    all_scenarios = {}
    for f in sys.argv[1:]:
        all_scenarios.update(parse(Path(f).read_text(encoding="utf-8")))
    for sid, dialoog in all_scenarios.items():
        path = SCENARIOS_DIR / f"{sid}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["dialoog"] = dialoog
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(sid, len(dialoog["knopen"]), "knopen")
