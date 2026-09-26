// Multiple-choice quiz used by scenarios (5 questions) and lessons (20 questions).
// questions: [{ question, options, correct, explanation? }]
(function () {
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  const LETTERS = ['a', 'b', 'c', 'd', 'e', 'f'];

  function prepare(questions) {
    return Store.shuffle(questions).map((q) => {
      const correctText = q.options[q.correct || 0];
      // "Alle bovenstaande" / "Beide a en c" only make sense in the original order.
      const options = Store.refersToOthers(q.options) ? q.options.slice() : Store.shuffle(q.options);
      return { question: q.question, options, correctIdx: options.indexOf(correctText), explanation: q.explanation };
    });
  }

  /**
   * opts.threshold(total) -> number needed to pass
   * opts.passLabel, opts.onPass(score,total)
   * opts.failText(threshold,total), opts.onBack (optional "Terug naar theorie")
   */
  function Quiz(root, questions, opts) {
    let qs, idx, score, answered;

    function start() {
      qs = prepare(questions);
      idx = 0;
      score = 0;
      answered = false;
      renderQuestion();
    }

    function renderQuestion() {
      const q = qs[idx];
      root.innerHTML = '';
      const prog = el('div', 'quiz-progress');
      prog.append(el('span', null, `Vraag ${idx + 1} van ${qs.length}`), el('span', null, `Score: ${score}`));
      root.append(prog, el('h2', 'quiz-question', q.question));

      const buttons = q.options.map((opt, i) => {
        const b = el('button', 'option');
        b.append(el('span', 'option-key', LETTERS[i]), el('span', null, opt));
        b.type = 'button';
        b.addEventListener('click', () => choose(i, buttons));
        root.append(b);
        return b;
      });
      root.append(el('div', 'quiz-after'));
      if (buttons[0]) buttons[0].focus({ preventScroll: true });
    }

    function choose(i, buttons) {
      if (answered) return;
      answered = true;
      const q = qs[idx];
      if (i === q.correctIdx) score++;
      buttons.forEach((b, j) => {
        b.disabled = true;
        if (j === q.correctIdx) b.classList.add('correct');
        else if (j === i) b.classList.add('wrong');
      });
      root.querySelector('.quiz-progress span:last-child').textContent = `Score: ${score}`;

      const after = root.querySelector('.quiz-after');
      if (q.explanation) after.append(el('div', 'explanation', q.explanation));
      const last = idx + 1 >= qs.length;
      const next = el('button', 'btn btn-primary block', last ? 'Bekijk resultaat' : 'Volgende vraag');
      next.type = 'button';
      next.addEventListener('click', () => {
        if (last) return renderResult();
        idx++;
        answered = false;
        renderQuestion();
      });
      after.append(next);
      next.focus({ preventScroll: true });
    }

    function renderResult() {
      const total = qs.length;
      const need = opts.threshold(total);
      const passed = score >= need;
      root.innerHTML = '';
      const box = el('div', 'result');
      box.append(el('p', 'page-label', 'Resultaat'));
      box.append(el('div', 'score ' + (passed ? 'pass' : 'fail'), `${score} / ${total}`));
      box.append(el('p', 'body-text', passed ? opts.passText : opts.failText(need, total)));

      if (passed) {
        const b = el('button', 'btn btn-primary block', opts.passLabel);
        b.type = 'button';
        b.addEventListener('click', () => opts.onPass(score, total));
        box.append(b);
      } else {
        const retry = el('button', 'btn btn-secondary block', 'Opnieuw proberen');
        retry.type = 'button';
        retry.addEventListener('click', start);
        box.append(retry);
        if (opts.onBack) {
          const back = el('button', 'btn-link', 'Terug naar theorie');
          back.type = 'button';
          back.addEventListener('click', opts.onBack);
          box.append(back);
        }
      }
      root.append(box);
    }

    // Keyboard: a-d or 1-4 picks an answer (Enter/Space on the focused "next" button continues).
    document.addEventListener('keydown', (e) => {
      if (!root.offsetParent || e.altKey || e.ctrlKey || e.metaKey) return;
      const tag = (e.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea') return;
      const key = e.key.toLowerCase();
      const n = LETTERS.includes(key) ? LETTERS.indexOf(key) + 1 : Number(key);
      const options = root.querySelectorAll('.option');
      if (n >= 1 && n <= options.length && !answered) {
        e.preventDefault();
        options[n - 1].click();
      }
    });

    this.start = start;
  }

  window.Quiz = Quiz;
})();
