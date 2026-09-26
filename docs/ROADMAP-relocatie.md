# Roadmap: Papiamentu Pa Bo als relocatie-taalapp

Ontstaan uit een reviewgesprek (sessie 2026-09-26) over hoe de app aansluit bij een
Nederlander die naar Curaçao verhuist — voor 3 maanden, 3 jaar, of voor altijd. Deze drie
profielen zijn de meetlat voor elke stap hieronder:

- **3 maanden** — moet nú overleven: groeten, boodschappen, een dokter, en vooral *horen*
  wat er terug wordt gezegd. Geen tijd voor 40 lessen.
- **3 jaar** — moet functioneren: werk, gezondheid, bureaucratie, met de buurman kunnen
  praten. Heeft actieve *productie* nodig, niet alleen herkennen.
- **Voor altijd** — wil erin opgaan: cultuur, idioom, uiteindelijk de brug naar echte
  Curaçaose media en de gemeenschap.

## Hoe dit document te gebruiken

Elke fase hieronder is een op zichzelf staand blokje werk: lees de fase, implementeer,
draai de tests (`.venv/Scripts/python -m pytest -q`), vink de stappen af, commit, en ga
verder naar de volgende fase. Fases zijn ruwweg in prioriteitsvolgorde maar niet allemaal
afhankelijk van elkaar — fase 2 (audio) kan bijvoorbeeld los van fase 3 (woordenschat-motor).

Blijf de bestaande conventies van deze repo volgen:
- Nederlandse UI-teksten, Papiamentu content met `lang="pap"`.
- Voortgang leeft client-side in `localStorage` via `papiamentu/static/js/store.js`
  (`Store.get()/update()`); alleen syncen naar de server als het écht moet, en dan via
  `papiamentu/sync.py` met een `_PROTECT_IF_MISSING`-achtige guard zodat een oudere tab
  nooit een nieuw veld leegtrekt (zie hoe `nieuws` en `xpEarned` dat al doen).
- Content in JSON onder `papiamentu/data/`, geladen via `papiamentu/content.py`.
- Nieuwe content krijgt een generator-script naar het voorbeeld van
  `scripts/gen_nieuws.py` (compact tekstformaat → JSON), zodat content bijmaken niet
  betekent dat je met de hand JSON schrijft.
- Elke nieuwe pagina/dataset krijgt een integriteitstest in `tests/test_app.py`, naar het
  voorbeeld van `test_nieuws_integrity`.
- Privacy-uitgangspunt van de opdrachtgever: zo min mogelijk persoonsgegevens. Geen bio,
  geen social/leaderboard-features met accounts. Lokaal-only en gedeeld-zonder-account
  (bv. een gegenereerde afbeelding) mag wel.

---

## Fase 1 — Uitspraak-knop (🔊) overal

**Waarom eerst:** raakt precies het gat dat het 3-maanden-profiel het hardst voelt
(nul audio in de hele app), en is met de browser's eigen `SpeechSynthesis`-API te bouwen
zonder server, hosting of kosten.

**Kanttekening vooraf:** geen browser heeft een Papiamentu-stem. Kies bij implementatie
de dichtstbijzijnde beschikbare stem (Spaans of Portugees geven een betere benadering dan
Nederlands of Engels) en zet dat ook zo in een tooltip/toelichting, zodat gebruikers niet
denken dat dit "de" Papiamentu-uitspraak is.

**Stappen:**
- [ ] Nieuwe kleine module `papiamentu/static/js/speak.js`: één functie
      `Speak.play(text)` die een `SpeechSynthesisUtterance` afvuurt met de beste
      beschikbare stem (kies via `speechSynthesis.getVoices()`, val terug op de browser-taal
      als er niets Papiamentu-achtigs is). Graceful no-op als `speechSynthesis` niet bestaat
      (Safari-quirks, oude browsers).
  - [ ] Voeg een klein 🔊-knopje toe naast elk stuk Papiamentu-tekst waar dat nu al
        losstaand gerenderd wordt: `word-pap` (scenario/les/nieuws), `news-quote`,
        `flashcard .fc-pap` (woorden.html), de scenario-`word-row`s.
  - [ ] CSS: klein, subtiel icoon-knopje (kijk naar `.icon-btn` in style.css, al gebruikt
      voor "ander woord" op de homepage — hergebruik die stijl).
- [ ] Test: geen Python-test mogelijk voor `SpeechSynthesis` zelf (browser-API); voeg wel
      een test toe die checkt dat `speak.js` op elke pagina met Papiamentu-tekst wordt
      ingeladen (`test_app.py`, simpele `assert 'speak.js' in html` per relevante route).
- [ ] Handmatig testen in de browserpreview: klik een 🔊-knop, controleer dat er geluid
      afgaat en dat de pagina niet breekt wanneer `speechSynthesis` ontbreekt (simuleer met
      `delete window.speechSynthesis` in de devtools console).

**Latere, hogere-kwaliteit stap (aparte fase, niet nu):** échte native-uitspraak laten
inspreken voor de ~100 hoogste-frequentiezinnen (zie Fase 3) en die als korte audiobestanden
serveren in plaats van TTS. Vergt een native speaker en audio-opslag — bewust uitgesteld.

---

## Fase 2 — Eén centrale woordenschat-motor (unified SRS)

**Waarom:** nu leven sleutelwoorden van scenario's (`introWords`/`words`), nieuws
(`sleutelwoorden`) en lessen (`woorden`) in aparte potjes die nergens terugkomen. Alleen de
6 vaste woordenlijsten in `woorden.html` krijgen spaced repetition. Een scenario-woord dat
je één keer ziet, kom je nooit meer tegen.

**Ontwerp:**
- Eén verzamel-lijst van alle woorden uit alle bronnen, met een `bron`-veld
  (`woordenlijst`/`scenario-007`/`nieuws-014`/`les-012`) zodat je kunt filteren, maar met
  dezelfde spaced-repetition-mechaniek als nu in `woorden.html` (`correct_count`,
  `is_mastered`, gewogen random pick op basis van recentheid).
- Voortgang blijft in `Store.get().woorden` (bestaand schema, per woord-id) — geen nieuwe
  synced-datastructuur nodig, alleen meer woord-ids die er binnenkomen.
- **Let op woord-id-uniciteit**: `woorden.json`-ids (`w1_01` etc.) mogen nooit botsen met
  scenario/nieuws/les-woord-ids. Geef nieuwe bron-woorden een genamespaced id, bv.
  `scenario-007:kaminda` of `nieuws-014:sushi`, zodat bestaande voortgang (`w1_01`...)
  gegarandeerd intact blijft — dit is een harde regel uit `papiamentu/content.py`'s
  documentatie: woord-id's nooit hergebruiken/laten botsen.

**Stappen:**
- [ ] `content.py`: bouw een `Content.alle_leerwoorden()` (of vergelijkbare methode) die
      over `woordenlijsten`, `scenarios`, `nieuws` en `lessen` itereert en een platte lijst
      teruggeeft van `{id, woord, uitspraak, vertaling, bron}`.
- [ ] Nieuwe route (of uitbreiding van `/woorden`) die deze volledige set naar de pagina
      stuurt, met een filter/toggle "alleen basiswoorden" vs "alles wat ik ben tegengekomen"
      — voorkomt dat een absolute beginner meteen met 300 woorden wordt overspoeld.
  - Overweeg: alleen woorden "vrijgeven" in deze motor zodra de gebruiker het scenario/
    nieuwsartikel/les waar ze vandaan komen heeft geopend — dus geen losse woordenlijst
    van dingen die je nog nooit hebt gezien.
- [ ] `tests/test_app.py`: test dat elk woord-id uniek is over de hele site (dit is
      precies zo'n test-vorm als de bestaande `assert len(word_ids) == len(set(word_ids))`
      in `test_content_integrity` — breid die test uit i.p.v. een nieuwe te schrijven).

---

## Fase 3 — Noodwoordenboek ("Eerste week op Curaçao")

**Waarom:** het 3-maanden-profiel komt nooit aan les 10 toe. Een vaste, korte, buiten de
lessenvolgorde staande lijst met de nuttigste ~50 zinnen dekt precies dat gat.

**Stappen:**
- [ ] Nieuw databestand `papiamentu/data/noodwoordenboek.json`: een simpele lijst van
      categorieën (Begroeten, Boodschappen, Nood/gezondheid, Onderweg, Basiszinnen) met per
      categorie 6-10 zinnen (`papiamentu`, `uitspraak`, `vertaling`).
- [ ] Nieuwe route `/eerste-week` + template, met dezelfde 🔊-knop uit Fase 1 op elke
      zin. Geen quiz, geen voortgang bijhouden — dit is naslag, geen oefening. (Puur lezen
      hoeft niet client-side te worden opgeslagen; dat past bij het privacy-uitgangspunt.)
  - [ ] Prominente kaart/knop op de homepage, zichtbaar vóór iemand een naam invult
        (dus ook in de onboarding-sectie van `home.html`), met een tekst die het
        3-maanden-profiel direct aanspreekt: "Net op Curaçao? Begin hier."
- [ ] `tests/test_app.py`: content-integriteitstest analoog aan `test_nieuws_integrity`
      (elke zin heeft niet-lege velden, geen dubbele ids).

---

## Fase 4 — Intake bij eerste bezoek ("Hoe lang blijf je?")

**Waarom:** operationaliseert het 3-profielen-model letterlijk. Kost geen backend: één
lokale voorkeur die bepaalt wat er prominent getoond wordt.

**Stappen:**
- [ ] Nieuw, niet-gesynct veld `Store.get().profielKeuze` (`'kort' | 'middel' | 'blijvend' |
      null`), analoog aan hoe `theme` en `weekXp` nu al puur lokaal blijven
      (uitsluiten in `forSync()` in `store.js`).
- [ ] Onboarding-scherm in `home.html`: na het invullen van de naam, één extra korte vraag
      met drie knoppen. Sla de keuze op en stuur meteen door:
      - *kort* → `/eerste-week` (Fase 3) + Easy-scenario's.
      - *middel* → dashboard zoals nu, met Nieuws lezen en lessen geaccentueerd.
      - *blijvend* → dashboard + een teaser voor Fase 8/9-content zodra die bestaat.
  - [ ] Laat het altijd overslaanbaar/wijzigbaar zijn vanuit Instellingen — dit is een
        suggestie, geen harde gate.
- [ ] Geen server-test nodig (puur client-side UI-keuze); wel een korte handmatige
      controle in de browserpreview dat alle drie de paden werken en dat "overslaan" het
      gewone dashboard toont.

---

## Fase 5 — Streak / terugkombonus

**Waarom:** ontbreekt volledig, en is de bekendste retentiehefboom in taal-apps. Kan
volledig lokaal, geen pushmeldingen nodig (die vereisen een heel ander soort infra).

**Stappen:**
- [ ] `store.js`: nieuw lokaal (niet-gesynct) veld `streak: { laatsteDag: 'YYYY-MM-DD',
      lengte: 0 }`. Bij elke `Store.addXp()`-aanroep: als `laatsteDag` gisteren was → `lengte
      + 1`; als het vandaag al was → niets doen; anders (gat van >1 dag) → reset naar 1.
  - Hergebruik het patroon van `isoWeekKey()` (al in `store.js` voor `weekXp`) voor de
    datumvergelijking, maar dan per dag i.p.v. per ISO-week.
- [ ] Klein streak-badge op de homepage (bv. "🔥 4 dagen op rij") en op `/profiel`.
- [ ] Overweeg een zachte reminder die **niet** afhankelijk is van serverinfra: een
      banner die verschijnt zodra je de site opnieuw bezoekt na een gemiste dag ("Je streak
      van 4 dagen is gisteren gestopt — vandaag weer beginnen?"). Geen echte notificaties;
      dat is bewust buiten scope gehouden vanwege de privacy-insteek (geen contactgegevens
      nodig, geen device-tokens).
- [ ] Geen serverwijziging nodig; wel een korte JS-sanity-check (handmatig, via
      localStorage-manipulatie in de browserpreview, zoals eerder in deze sessie gedaan bij
      `weekXp`) dat de streak goed doortelt en resettet.

---

## Fase 6 — Vertakte dialogen in scenario's

**Waarom:** het grootste structurele gat voor het 3-jaar-profiel: bijna alles is nu
*herkennen* (meerkeuze), niets is *actief spreken/reageren*. Een vertakte dialoog — kies
wat je zelf zegt, de winkelier/dokter reageert anders per keuze — komt veel dichter bij
communicatieve competentie.

**Dit is de grootste fase hier — plan hem als een aparte mini-project, niet als één zitting.**

**Ontwerp:**
- Nieuw content-veld per scenario (optioneel, niet elk scenario hoeft dit meteen te
  hebben): `dialoog`, een boom van knopen `{ npc_zegt, keuzes: [{ tekst, gaat_naar,
  feedback? }] }`. Begin met 2-3 scenario's als proof of concept (bv. scenario-005
  "Boodschappen doen" en scenario-010 "Bij de dokter" — hoogfrequent en herkenbaar).
- Herbruik zoveel mogelijk van de bestaande `Quiz.ask`-stijl (uit `quiz.js`) voor de
  interactie-mechaniek (knoppen, keyboard a-d, disabled-na-klik), maar dan aangestuurd
  door een boomstructuur i.p.v. een vaste vragenlijst.
- Geen "fout antwoord = game over": een minder ideale keuze leidt naar een tak die het
  gesprek laat haperen (en uitlegt waarom), niet naar een dood punt — blijft in lijn met
  de huidige, foutvriendelijke toon van de app.

**Stappen:**
- [ ] Datamodel + JSON-schema bedenken, documenteren in `content.py`-achtige comments.
- [ ] Contentgenerator-script `scripts/gen_dialoog.py` naar het voorbeeld van
      `scripts/gen_nieuws.py` (compact tekstformaat, geen handmatig geneste JSON).
- [ ] Front-end: nieuwe sectie binnen `scenario.html` (of een nieuw `data-type="dialoog"`
      naast de bestaande `intro/grammar/words/pitfalls/culture/quiz`-pagina's).
- [ ] Tests: content-integriteit (elke `gaat_naar` verwijst naar een bestaande knoop, geen
      dead ends zonder keuzes tenzij het een eindknoop is).
- [ ] Na de eerste 2-3 scenario's: evalueren of dit de moeite waard is vóór je alle 20
      scenario's ombouwt.

---

## Fase 7 — Cultuurmodule (hergebruik van de Nieuws-motor)

**Waarom:** voor het "voor altijd"-profiel. De Nieuws-leesmotor (alinea → vraag-per-zin →
alinea-vraag, met vertaling-voor-XP) is al gebouwd en generiek genoeg om te hergebruiken
voor iets anders dan nieuws: lokale gewoontes, geschiedenis, tambú/seú, Nederland-Curaçao-
gevoeligheden — respectvol en informatief, niet alleen anekdotisch zoals de huidige losse
"did-you-know"-blokjes in scenario's.

**Stappen:**
- [ ] Overweeg om `nieuws_artikel.html`/`nieuws.html` te generaliseren naar een gedeelde
      "leesoefening"-component die zowel `/nieuws` als een nieuwe `/cultuur` voedt, in
      plaats van het bestand te kopiëren — voorkomt dat een bugfix straks op twee plekken
      moet.
- [ ] Zelfde vrijspeel-mechaniek als nieuws (`NIEUWS_UNLOCK`-patroon) kan hergebruikt
      worden, of bewust achterwege gelaten als cultuurstukken meteen allemaal open moeten
      zijn (bespreek dit met de opdrachtgever voordat je bouwt — is nog geen besluit).
- [ ] Content: laat een aantal stukken door een moedertaalspreker beoordelen vóór publicatie
      — dit soort onderwerpen (koloniale geschiedenis, Nederland-relatie) is gevoeliger dan
      een verzonnen nieuwsbericht over een ontsnapte geit.

---

## Fase 8 — Praktische relocatie-scenario's

**Waarom:** de sterkste kant van de app (relocatie-specifieke scenario's) heeft nog
duidelijke gaten. Dit is puur content, geen nieuwe techniek — dezelfde
`scenario-XXX.json`-vorm als nu.

**Nieuwe scenario's om toe te voegen** (elk: intro, grammatica-oefenzinnen, woordenschat,
valkuilen, cultuur, quiz — zoals de bestaande 20):
- [ ] **Sédula aanvragen** (verblijfsdocument) — waarschijnlijk de meest voorkomende
      bureaucratische stap voor élke relocatie-duur.
- [ ] **Een huis huren** (huurcontract, borg, oplevering) — momenteel wel "loodgieter over
      lekkage" maar niet het aangaan van de huur zelf.
- [ ] **Een huisdier meenemen/importeren** (quarantaine, papieren) — veelvoorkomend en
      emotioneel beladen pijnpunt bij NL→CW-verhuizingen.
- [ ] **Zorgverzekering (SVB) regelen** — naast het bestaande "bij de dokter"-scenario.
- [ ] **Een kind op school inschrijven** (Papiamentu- vs Nederlandstalig onderwijs) —
      relevant voor het 3-jaar/voor-altijd-profiel met gezin.
- [ ] **Orkaanseizoen: voorbereiden op een storm** — praktisch én veiligheidsrelevant,
      en een onderwerp dat een Nederlander simpelweg niet kent.
- [ ] Voeg elk scenario toe aan `papiamentuPaBoScenarios.json` (lijst-metadata) én
      `papiamentu/data/scenarios/scenario-0XX.json` (volledige inhoud) — zie de
      "Layout"-sectie in `README.md` voor hoe die twee samenhangen.
- [ ] Draai `test_content_integrity` na elke toevoeging.

---

## Fase 9 — Uitstroom naar echte content

**Waarom:** na lesson 40 / scenario 20 / nieuws-038 stopt de app hard. Voor het
"voor altijd"-profiel is de eigenlijke stap "de app achter je laten en de taal in het echt
gebruiken."

**Stappen:**
- [ ] Een "Wat nu?"-pagina of -sectie die verschijnt zodra iemand het curriculum
      (nagenoeg) heeft afgerond: verwijzingen naar échte Papiamentu-media (extra.cw zelf,
      TeleCuraçao, lokale radio/podcasts), met een korte duiding van het niveau/tempo dat ze
      te wachten staat.
  - [ ] Noem ook expliciet het verschil met Aruba/Bonaire-Papiamentu(spelling), zodat
        iemand niet in de war raakt als hij ineens Arubaanse spelling tegenkomt.
- [ ] Geen taalmaatje-matching-systeem bouwen (dat vereist accounts/persoonsgegevens,
      botst met de privacy-insteek) — beperk je tot statische verwijzingen naar bestaande
      lokale initiatieven, eventueel met een link/contactformulier-suggestie via de
      bestaande `/contact`-pagina.

---

## Fase 10 (optioneel) — Lokaal deelbaar medaille-plaatje

**Waarom:** de opdrachtgever wees social/leaderboard-features expliciet af vanwege de
privacy-insteek, maar noemde zelf dat iets **lokaals** wel leuk zou kunnen zijn. Dit is de
sociale prikkel zonder account of server-opslag.

**Stappen:**
- [ ] Op `/profiel`: een knop "Deel je medaille" die client-side (canvas of een SVG →
      `toDataURL()`) een vierkante afbeelding genereert met de behaalde medaille, het
      thermometer-plaatje en eventueel de gekozen naam — en die aanbiedt als download
      (`<a download>`), niet als automatische upload/post ergens naartoe.
  - Geen serverstap, geen account, geen tracking — precies in lijn met "zo min mogelijk
    persoonsgegevens verwerken."
- [ ] Test: handmatig in de browserpreview — genereer de afbeelding, controleer dat hij
      klopt met de actuele medaille/thermometerstand.

---

## Suggestie voor volgorde

1. Fase 1 (audio) en Fase 3 (noodwoordenboek) — snelste, grootste winst voor het
   meest onderbediende profiel (3 maanden).
2. Fase 4 (intake) — bindt 1 en 3 samen tot een samenhangende eerste-bezoek-ervaring.
3. Fase 2 (woordenschat-motor) en Fase 5 (streak) — versterken wat er al is, matig werk.
4. Fase 8 (relocatie-scenario's) — puur content, kan parallel aan alles.
5. Fase 6 (vertakte dialogen) — grootste technische klus, apart plannen.
6. Fase 7 en 9 — voor het "voor altijd"-profiel, logisch pas later.
7. Fase 10 — leuke, kleine toevoeging, geen haast.
