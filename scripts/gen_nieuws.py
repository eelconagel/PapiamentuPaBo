"""Turn the compact article text format into nieuws-XXX.json files.

Usage: python scripts/gen_nieuws.py <start-number> <source.txt> [more.txt ...]
Writes papiamentu/data/nieuws/nieuws-<NNN>.json for every article found, numbered
consecutively starting at <start-number> (ids must stay a gap-free 001, 002, ... sequence,
since the reading order also drives the unlock order — see NIEUWS_UNLOCK in content.py).

Compact format (one or more articles per source file):

=== titel | nivo | kategoria | lugá
> beschrijving
W woord ; uitspraak ; vertaling
Z <Papiamentu sentence>
N <Dutch translation>
? <optional own question>
+ <correct option>
- <wrong option>            (2-4 of these)
: <explanation>
A <optional paragraph question>   (closes the paragraph; followed by + / - / :)

Each "Z" line starts a new sentence question; "A" closes the current paragraph with its own
question. Multiple-choice options are rotated deterministically so the correct answer isn't
always first. After generating, run the test suite (test_nieuws_integrity) to check the
JSON shape, and have a native speaker review the Papiamentu before publishing.
"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "papiamentu" / "data" / "nieuws"
_n = [0]


def place(correct, wrong):
    _n[0] += 1
    opts = [correct] + wrong
    k = _n[0] % len(opts)
    opts = opts[-k:] + opts[:-k] if k else opts
    return opts, opts.index(correct)


def parse(text):
    arts, art, para, q = [], None, None, None

    def close_q():
        nonlocal q, para
        if q is None:
            return
        opts, c = place(q.pop("_plus"), q.pop("_min"))
        target = q.pop("_target")
        q["opties"], q["correct"] = opts, c
        if "_uitleg" in q:
            q["uitleg"] = q.pop("_uitleg")
        if target == "zin":
            para["zinnen"].append({k: q[k] for k in ("pap", "nl", "vraag", "opties", "correct", "uitleg") if k in q})
        else:
            para.update({"vraag": q.get("vraag") or "Waar gaat deze alinea over?", "opties": q["opties"],
                         "correct": q["correct"], "uitleg": q.get("uitleg", "")})
            art["paragrafen"].append({"zinnen": para["zinnen"], "vraag": para["vraag"], "opties": para["opties"],
                                      "correct": para["correct"], "uitleg": para["uitleg"]})
            para = None
        q = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tag, _, rest = line.partition(" ")
        rest = rest.strip()
        if tag == "===":
            close_q()
            titel, nivo, kat, lug = [x.strip() for x in rest.split("|")]
            art = {"titel": titel, "nivo": nivo, "kategoria": kat, "lugá": lug, "beschrijving": "",
                   "paragrafen": [], "sleutelwoorden": []}
            arts.append(art)
        elif tag == ">":
            art["beschrijving"] = rest
        elif tag == "W":
            w, u, v = [x.strip() for x in rest.split(";")]
            art["sleutelwoorden"].append({"woord": w, "uitspraak": u, "vertaling": v})
        elif tag == "Z":
            close_q()
            if para is None:
                para = {"zinnen": []}
            q = {"_target": "zin", "pap": rest, "_min": []}
        elif tag == "N":
            q["nl"] = rest
        elif tag == "?":
            q["vraag"] = rest
        elif tag == "A":
            close_q()
            q = {"_target": "alinea", "vraag": rest, "_min": []}
        elif tag == "+":
            q["_plus"] = rest
        elif tag == "-":
            q["_min"].append(rest)
        elif tag == ":":
            q["_uitleg"] = rest
        else:
            raise ValueError(f"unknown line: {raw!r}")
    close_q()
    return arts


if __name__ == "__main__":
    start = int(sys.argv[1])
    arts = []
    for f in sys.argv[2:]:
        arts += parse(Path(f).read_text(encoding="utf-8"))
    for i, a in enumerate(arts, start=start):
        aid = f"nieuws-{i:03d}"
        data = {"id": aid, **a}
        (OUT / f"{aid}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8", newline="\n")
        print(aid, a["nivo"], len(a["paragrafen"]), sum(len(p["zinnen"]) for p in a["paragrafen"]))
