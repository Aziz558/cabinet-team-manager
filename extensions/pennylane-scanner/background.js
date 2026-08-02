(() => {
  'use strict';

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'GET_SETTINGS') {
      chrome.storage.sync.get(['openrouterApiKey', 'openrouterModel'], (items) => {
        sendResponse({
          apiKey: (items.openrouterApiKey || '').trim(),
          model: (items.openrouterModel || '').trim()
        });
      });
      return true;
    }

    if (message.type === 'ANALYZE_WITH_LLM') {
      handleAnalyzeWithLLM(message.apiKey, message.model, message.pageText)
        .then(result => sendResponse(result))
        .catch(error => sendResponse({ items: [], error: error.message }));
      return true;
    }

    if (message.type === 'SEND_TO_BACKEND') {
      handleSendToBackend(message.payload)
        .then(result => sendResponse(result))
        .catch(error => sendResponse({ ok: false, message: error.message }));
      return true;
    }
  });

  async function handleAnalyzeWithLLM(apiKey, model, pageText) {
    const prompt = `Tu es un assistant comptable. Analyse le texte suivant extrait d'une page PennyLane de factures fournisseurs ou clients ou transactions. Extrait uniquement les éléments utiles à la réconciliation comptable : numéro de facture, date, fournisseur/client, montant HT/TTC, statut. Formate la réponse en JSON valide sans markdown, avec cette structure : { "items": [ { "type": "supplier_invoice"|"customer_invoice"|"transaction", "number": "...", "date": "YYYY-MM-DD", "party": "...", "amount_ht": number, "amount_ttc": number, "status": "..." } ] }. Si rien n'est exploitable, renvoie { "items": [] }. Voici le texte :\n\n${pageText}`;

    const response = await fetch('https://openrouter.ai/api/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`
      },
      body: JSON.stringify({
        model: model,
        messages: [
          { role: 'user', content: prompt }
        ],
        temperature: 0
      })
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`OpenRouter HTTP ${response.status}: ${text.slice(0, 120)}`);
    }

    const data = await response.json();
    const content = data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content;
    if (!content) {
      throw new Error('Réponse OpenRouter vide');
    }

    const cleaned = content.replace(/^```json\n?|\n?```$/g, '').trim();
    try {
      return JSON.parse(cleaned);
    } catch (e) {
      throw new Error('Réponse LLM non JSON: ' + cleaned.slice(0, 120));
    }
  }

  async function handleSendToBackend(payload) {
    const response = await fetch('http://localhost:5000/api/pennyane/extension', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const text = await response.text();
    try {
      return JSON.parse(text);
    } catch (e) {
      return { ok: false, message: 'Réponse backend invalide: ' + text.slice(0, 120) };
    }
  }
})();
