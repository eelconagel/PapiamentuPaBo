// Uitspraak-knop op basis van de browser's ingebouwde spraaksynthese (Web Speech API).
// Geen server, geen audiobestanden nodig — maar ook geen browser heeft een Papiamentu-stem,
// en de dichtstbijzijnde beschikbare stem (Portugees/Spaans) bleek in de praktijk geen goede
// benadering. TIJDELIJK UITGEZET (FEATURE_ENABLED = false) tot er echte, door een moedertaal-
// spreker ingesproken audio is — zie docs/ROADMAP-relocatie.md Fase 1. De aanroepen
// (Speak.attach/attachAll) blijven overal in de templates staan; zet FEATURE_ENABLED hier
// terug op true (of vervang play() door echte audioclips) om de knop weer te laten zien.
(function () {
  const FEATURE_ENABLED = false;
  const available = FEATURE_ENABLED && 'speechSynthesis' in window;
  let cachedVoice = null;
  let voicesReady = false;

  function pickVoice() {
    if (!available) return null;
    const voices = speechSynthesis.getVoices();
    if (!voices.length) return null;
    voicesReady = true;
    const byPrefix = (prefix) => voices.find((v) => v.lang && v.lang.toLowerCase().startsWith(prefix));
    return byPrefix('pt') || byPrefix('es') || byPrefix('nl') || voices[0];
  }

  if (available) {
    cachedVoice = pickVoice();
    // Voices load asynchronously in some browsers (notably Chrome on first visit).
    speechSynthesis.addEventListener('voiceschanged', () => { cachedVoice = pickVoice(); });
  }

  function play(text) {
    if (!available || !text || !text.trim()) return;
    speechSynthesis.cancel();  // don't queue: a new click replaces whatever was playing
    const utter = new SpeechSynthesisUtterance(text.trim());
    const voice = cachedVoice || pickVoice();
    if (voice) { utter.voice = voice; utter.lang = voice.lang; }
    utter.rate = 0.9;  // iets langzamer: makkelijker te volgen voor een beginner
    speechSynthesis.speak(utter);
  }

  // Bouwt een los 🔊-knopje dat `text` uitspreekt. `label` is voor screenreaders; de title
  // legt uit dat dit een benadering is, geen echte Papiamentu-stem.
  function button(text, label) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'speak-btn';
    b.setAttribute('aria-label', label || `Beluister uitspraak van "${text}"`);
    b.title = 'Beluister uitspraak (benaderde uitspraak — geen browser heeft een Papiamentu-stem)';
    b.textContent = '🔊';
    b.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();  // niet de klik van een omliggend klikbaar element triggeren
      play(text);
    });
    if (!available) b.hidden = true;
    return b;
  }

  // Voegt een knopje toe als laatste kind van `el` (werkt voor zowel inline als blok-
  // elementen: het knopje komt gewoon op dezelfde regel als het laatste stukje tekst).
  // Gebruikt `el`'s eigen tekst als uit te spreken tekst, tenzij `textOverride` is gegeven.
  // Doet niets als er al een knopje in zit (voorkomt dubbele knoppen bij herhaald renderen).
  function attach(el, textOverride) {
    if (!available || !el || el.querySelector(':scope > .speak-btn')) return;
    const text = textOverride ?? el.textContent;
    el.appendChild(button(text));
  }

  // Voegt aan alle elementen die `selector` matchen (binnen `root`) een knopje toe.
  function attachAll(selector, root) {
    (root || document).querySelectorAll(selector).forEach((el) => attach(el));
  }

  window.Speak = { available, play, button, attach, attachAll };
})();
