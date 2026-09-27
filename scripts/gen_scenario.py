"""Turn a compact scenario text format into full scenario-XXX.json files, matching the
shape used throughout papiamentu/data/scenarios/*.json.

Usage: python scripts/gen_scenario.py <source.txt> [more.txt ...]
Writes papiamentu/data/scenarios/<id>.json for every scenario found. Does NOT touch
papiamentuPaBoScenarios.json (the list metadata) — add an entry there by hand for each
new scenario so it shows up on /scenarios.

Compact format (one or more scenario's per source file):

=== <id> | <title> | <difficulty> | <category>
INTRO <intro text>
IW <papiamentu> ; <uitspraak> ; <dutch>              (introWords, one or more)
GTITLE <grammatica-titel>
GEXPL <uitleg-regel>                                  (grammar.explanation, one or more)
EX <vraag> || <opt1> | <opt2> | <opt3> | <opt4> || <correct 0-based> || <uitleg>
W <papiamentu> ; <uitspraak> ; <dutch> ; [voorbeeldzin]   (words, one or more)
PITFALL <valkuil> || <detail> || <om te onthouden>
CTITLE <cultuur-titel>
CINTRO <cultuur-intro>
CFACT <feit>                                          (culture.facts, one or more)
CDYK <wist-je-dat>
Q <vraag> || <opt1> | <opt2> | <opt3> | <opt4> || <correct 0-based> || <uitleg>   (quiz, 5x)

<difficulty> is één van: Easy, Intermediate, Hard, Native Speaker (zie content.py
NIVEAU_LABEL). Elk scenario moet minimaal 3 EX-regels, 5 Q-regels en 4 W-regels hebben —
de content-integriteitstest in tests/test_app.py controleert dit soort dingen niet
allemaal, dus check de output ook met /scenarios/<id> in de browser.
"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "papiamentu" / "data" / "scenarios"


def _q(line):
    vraag, opts, correct, uitleg = line.split("||")
    return {"question": vraag.strip(), "options": [o.strip() for o in opts.split("|")],
            "correct": int(correct.strip()), "explanation": uitleg.strip()}


def parse(text):
    scenarios = []
    s = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tag, _, rest = line.partition(" ")
        rest = rest.strip()
        if tag == "===":
            sid, title, diff, cat = [x.strip() for x in rest.split("|")]
            s = {"id": sid, "title": title, "difficulty": diff, "category": cat, "intro": "",
                 "introWords": [], "grammar": {"title": "", "explanation": [], "exercises": []},
                 "words": [], "pitfalls": [], "culture": {"title": "", "intro": "", "facts": []},
                 "quiz": []}
            scenarios.append(s)
        elif tag == "INTRO":
            s["intro"] = rest
        elif tag == "IW":
            pap, uit, nl = [x.strip() for x in rest.split(";")]
            s["introWords"].append({"papiamentu": pap, "pronunciation": uit, "dutch": nl})
        elif tag == "GTITLE":
            s["grammar"]["title"] = rest
        elif tag == "GEXPL":
            s["grammar"]["explanation"].append(rest)
        elif tag == "EX":
            s["grammar"]["exercises"].append(_q(rest))
        elif tag == "W":
            parts = [x.strip() for x in rest.split(";")]
            pap, uit, nl = parts[0], parts[1], parts[2]
            w = {"papiamentu": pap, "pronunciation": uit, "dutch": nl}
            if len(parts) > 3 and parts[3]:
                w["example"] = parts[3]
            s["words"].append(w)
        elif tag == "PITFALL":
            trap, detail, remember = [x.strip() for x in rest.split("||")]
            s["pitfalls"].append({"trap": trap, "detail": detail, "remember": remember})
        elif tag == "CTITLE":
            s["culture"]["title"] = rest
        elif tag == "CINTRO":
            s["culture"]["intro"] = rest
        elif tag == "CFACT":
            s["culture"]["facts"].append(rest)
        elif tag == "CDYK":
            s["culture"]["didYouKnow"] = rest
        elif tag == "Q":
            s["quiz"].append(_q(rest))
        else:
            raise ValueError(f"onbekende regel: {raw!r}")
    return scenarios


if __name__ == "__main__":
    for f in sys.argv[1:]:
        for s in parse(Path(f).read_text(encoding="utf-8")):
            path = OUT / f"{s['id']}.json"
            path.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
            print(s["id"], s["difficulty"], len(s["words"]), "woorden", len(s["quiz"]), "quizvragen")
