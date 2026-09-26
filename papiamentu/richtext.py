"""Turn the plain lesson texts (blank lines, "•" bullets, "KOPJE:" lines) into readable HTML."""
import re

from markupsafe import Markup, escape

_HEADING = re.compile(r"^(.{3,80}?)\s*:\s*(.*)$")
_LABEL = _HEADING
_BULLET = re.compile(r"^\s*[•·\-–]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*(\d{1,2})[.)]\s+(.*)$")


def _is_caps_heading(line: str) -> bool:
    letters = [c for c in re.sub(r"\([^)]*\)", "", line) if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


_PROPER = {w.lower(): w for w in ("Nederlands", "Curaçao", "Kòrsou", "Papiamentu", "Papiamento", "Aruba",
                                    "Bonaire", "Engels", "Spaans", "Portugees", "Afrikaans", "Arowaks")}


def _tidy(heading: str) -> str:
    """'DE BASISSTRUCTUUR (tabata)' -> 'De basisstructuur (tabata)'; keeps text in brackets and proper names."""
    parts = re.split(r"(\([^)]*\))", heading.strip())
    out = "".join(p if p.startswith("(") else p.lower() for p in parts)
    out = re.sub(r"[^\W\d_]+", lambda m: _PROPER.get(m.group(0), m.group(0)), out)
    return out[:1].upper() + out[1:]


def rich(text: str) -> Markup:
    if not text:
        return Markup("")
    html = []
    for block in re.split(r"\n\s*\n", text.strip()):
        para, items, kind = [], [], None

        def flush_para():
            if para:
                html.append("<p>" + "<br>".join(para) + "</p>")
                para.clear()

        def flush_list():
            nonlocal kind
            if items:
                html.append("<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
                items.clear()
            kind = None

        for raw in block.split("\n"):
            line = raw.strip()
            if not line:
                continue
            if m := _BULLET.match(line):
                flush_para()
                kind = "ul"
                items.append(str(escape(m.group(1))))
                continue
            if m := _NUMBERED.match(line):
                flush_para()
                flush_list()
                body = m.group(2)
                label = _LABEL.match(body)
                if label and _is_caps_heading(label.group(1)):
                    body_html = f"<strong>{escape(_tidy(label.group(1)))}:</strong> {escape(label.group(2))}"
                else:
                    body_html = str(escape(body))
                html.append(f'<p class="rich-num"><span class="num">{m.group(1)}</span><span>{body_html}</span></p>')
                continue
            flush_list()
            m = _HEADING.match(line)
            if m and _is_caps_heading(m.group(1)):
                flush_para()
                html.append(f'<h3 class="rich-h">{escape(_tidy(m.group(1)))}</h3>')
                if m.group(2):
                    para.append(str(escape(m.group(2))))
            elif _is_caps_heading(line) and len(line) < 60:
                flush_para()
                html.append(f'<h3 class="rich-h">{escape(_tidy(line))}</h3>')
            else:
                para.append(str(escape(line)))
        flush_list()
        flush_para()
    return Markup("\n".join(html))
