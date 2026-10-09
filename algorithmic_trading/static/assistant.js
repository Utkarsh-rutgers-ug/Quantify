// Plain text rendering keeps news and model output out of executable HTML.
(() => {
  const history = [];
  let conversationVersion = 0;
  const select = document.getElementById('briefingSelect');
  const status = document.getElementById('briefingStatus');
  const report = document.getElementById('briefingReport');
  const evidence = document.getElementById('briefingEvidence');
  let briefings = [];
  const time = value => value ? new Date(value).toLocaleString() : 'unknown';

  function showBriefing() {
    const row = briefings.find(item => String(item.id) === select.value);
    evidence.replaceChildren();
    if (!row) {
      status.textContent = 'Waiting for the first hourly collection.';
      report.textContent = 'Start Quantify with run.py, or keep worker.py running for scheduled collection.';
      return;
    }
    status.textContent = `${row.status.replaceAll('_', ' ')} · collected ${time(row.started_at)}${row.stale ? ' · OLD DATA' : ''}`;
    report.textContent = row.report || 'Collecting sources and preparing the briefing…';
    const data = row.evidence;
    const note = document.createElement('p');
    note.textContent = data.coverage || '';
    evidence.append(note);
    for (const feed of data.feeds || []) {
      if (feed.status !== 'ok') {
        const warning = document.createElement('p');
        warning.textContent = `${feed.source}: collection unavailable this run.`;
        evidence.append(warning);
      }
    }
    if (data.watchlist_total > data.watchlist_limit) {
      const warning = document.createElement('p');
      warning.textContent = `This briefing covers the first ${data.watchlist_limit} of ${data.watchlist_total} watched symbols.`;
      evidence.append(warning);
    }
    for (const quote of data.quotes || []) {
      const line = document.createElement('p');
      line.textContent = quote.status === 'observed'
        ? `[${quote.id}] ${quote.ticker}: $${quote.price.toFixed(2)} · ${quote.change_percent.toFixed(2)}% versus previous close · market time ${time(quote.market_timestamp)} · retrieved ${time(quote.retrieved_at)}`
        : `[${quote.id}] ${quote.ticker}: quote unavailable.`;
      evidence.append(line);
    }
    for (const item of data.news || []) {
      const line = document.createElement('p');
      const link = document.createElement('a');
      link.textContent = `[${item.id}] ${item.title}`;
      try {
        const url = new URL(item.url);
        if (['https:', 'http:'].includes(url.protocol)) link.href = url.href;
      } catch (_) { /* invalid source URLs remain text */ }
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      line.append(link, document.createTextNode(` · ${item.source} · published ${time(item.published_at)} · topic estimate: ${item.classification?.topic || 'unclassified'}`));
      evidence.append(line);
    }
  }

  async function refresh() {
    try {
      const data = await api('/assistant/briefings');
      const chosen = select.value;
      const wasLatest = !briefings.length || chosen === String(briefings[0].id);
      briefings = data.briefings;
      select.replaceChildren();
      for (const row of briefings) {
        const option = document.createElement('option');
        option.value = row.id;
        option.textContent = time(row.started_at);
        select.append(option);
      }
      if (!wasLatest && briefings.some(row => String(row.id) === chosen)) select.value = chosen;
      showBriefing();
    } catch (error) {
      status.textContent = error.message;
    }
  }
  select.addEventListener('change', showBriefing);
  document.getElementById('briefingReload').addEventListener('click', refresh);

  const form = document.getElementById('assistantForm');
  const input = document.getElementById('assistantMessage');
  const send = document.getElementById('assistantSend');
  const conversation = document.getElementById('assistantConversation');
  function appendMessage(label, text) {
    const row = document.createElement('p');
    const title = document.createElement('strong');
    title.textContent = label + '\n';
    row.append(title, document.createTextNode(text));
    conversation.append(row);
    conversation.scrollTop = conversation.scrollHeight;
    return row;
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message || send.disabled) return;
    if (!currentUserId) { appendMessage('Quantify', 'Select a trader first.'); return; }
    const username = document.getElementById('userSelect').selectedOptions[0]?.textContent.replace(/ \(#\d+\)$/, '') || 'Trader';
    appendMessage(username, message);
    input.value = '';
    send.disabled = true;
    const version = conversationVersion;
    const pending = appendMessage('Quantify', 'Reading the latest saved evidence…');
    try {
      const result = await api('/assistant/chat', {
        method: 'POST', body: JSON.stringify({message, user_id: Number(currentUserId), history: history.slice(-6)})
      });
      if (version !== conversationVersion) return;
      pending.remove();
      appendMessage('Quantify', `${result.answer}\n\nEvidence: ${time(result.evidence_as_of)} · briefing #${result.briefing_id}${result.stale ? ' · OLD DATA' : ''}\nPaper account read: ${time(result.portfolio_as_of)}`);
      history.push({role: 'user', content: message}, {role: 'assistant', content: result.answer.slice(0, 2000)});
      if (history.length > 6) history.splice(0, history.length - 6);
    } catch (error) {
      if (version !== conversationVersion) return;
      pending.textContent = error.message;
      input.value = message;
    } finally {
      send.disabled = false;
    }
  });
  document.getElementById('userSelect').addEventListener('change', () => {
    conversationVersion += 1;
    history.length = 0;
    conversation.replaceChildren();
    input.value = '';
  });
  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, 60000);
})();
