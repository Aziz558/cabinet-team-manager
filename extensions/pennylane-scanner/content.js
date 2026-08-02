(() => {
  'use strict';

  if (document.getElementById('pl-scanner-root')) return;

  const root = document.createElement('div');
  root.id = 'pl-scanner-root';
  root.innerHTML = `
    <button id="pl-scanner-btn" type="button">Scanner PennyLane</button>
    <div id="pl-scanner-result" class="pl-hidden"></div>
  `;
  document.body.appendChild(root);

  const btn = root.querySelector('#pl-scanner-btn');
  const result = root.querySelector('#pl-scanner-result');

  function show(text, cssClass = '') {
    result.className = cssClass;
    result.innerHTML = text;
    result.classList.remove('pl-hidden');
  }

  async function getOpenRouterSettings() {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: 'GET_SETTINGS' }, (response) => {
        resolve(response || { apiKey: '', model: '' });
      });
    });
  }

  btn.addEventListener('click', async () => {
    show('Analyse en cours...', '');

    const url = window.location.href;
    const rows = Array.from(document.querySelectorAll('table tbody tr, [role="row"], .row, tr'));
    const results = [];
    for (const row of rows) {
      const cells = Array.from(row.querySelectorAll('td, th, [role="cell"]'));
      if (!cells.length) continue;
      const text = cells.map(c => (c.textContent || '').trim()).join(' | ');
      if (!text) continue;
      results.push(text);
    }
    const match = url.match(/\/companies\/(\d+)\//);
    const companyId = match ? match[1] : '';

    if (!companyId) {
      show('Page non reconnue.', 'ko');
      return;
    }

    const settings = await getOpenRouterSettings();
    if (!settings.apiKey) {
      show("Clé API OpenRouter manquante. Ouvrez le popup de l'extension pour la saisir.", 'ko');
      return;
    }

    const pageText = results.slice(0, 50).join('\n');

    try {
      const llmResult = await chrome.runtime.sendMessage({
        type: 'ANALYZE_WITH_LLM',
        apiKey: settings.apiKey,
        model: settings.model,
        pageText
      });

      const items = Array.isArray(llmResult.items) ? llmResult.items : [];
      const fact_frs = items.filter(i => i.type === 'supplier_invoice').length;
      const fact_clts = items.filter(i => i.type === 'customer_invoice').length;
      const transactions = items.filter(i => i.type === 'transaction').length;

      const payload = {
        company_id: companyId,
        company_name: '',
        fact_frs,
        fact_clts,
        transactions,
        ecritures_attente: 0,
        documents_a_approuver: 0,
        raw: JSON.stringify({ url, items: items.slice(0, 20) })
      };

      const response = await chrome.runtime.sendMessage({
        type: 'SEND_TO_BACKEND',
        payload
      });

      let data = response;
      if (typeof response === 'string') {
        try { data = JSON.parse(response); } catch { data = {}; }
      }

      if (!data || data.ok === false) {
        const msg = (data && data.message) ? data.message : 'Erreur inconnue';
        show('Échec : ' + msg, 'ko');
        return;
      }

      let html = '<span class="ok">Statut : OK</span><br>';
      if (data.message) html += 'Message : ' + data.message + '<br>';
      if (data.changes && Object.keys(data.changes).length) {
        html += '<span class="change">Changements :</span><br>';
        for (const [key, value] of Object.entries(data.changes)) {
          html += '&nbsp;&nbsp;- ' + key + ' : ' + value.previous + ' -> ' + value.current + '<br>';
        }
      }
      html += '<br><span class="change">LLM :</span><br>';
      html += '&nbsp;&nbsp;Factures fournisseurs : ' + fact_frs + '<br>';
      html += '&nbsp;&nbsp;Factures clients : ' + fact_clts + '<br>';
      html += '&nbsp;&nbsp;Transactions : ' + transactions + '<br>';
      html += '&nbsp;&nbsp;Modèle : ' + settings.model + '<br>';
      show(html, '');
    } catch (error) {
      show('Erreur : ' + error.message, 'ko');
    }
  });
})();
