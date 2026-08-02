(() => {
  'use strict';

  const status = document.getElementById('status');
  const apiKeyInput = document.getElementById('apiKey');
  const modelInput = document.getElementById('model');
  const saveBtn = document.getElementById('save');
  let fetchAbortController = null;

  function setStatus(html, cssClass = '') {
    status.innerHTML = html;
    status.className = cssClass;
  }

  function setModelOptions(models, selectedModel) {
    modelInput.innerHTML = '';
    if (!models.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = 'Aucun modèle disponible';
      modelInput.appendChild(option);
      modelInput.disabled = true;
      return;
    }

    modelInput.disabled = false;
    models.forEach(model => {
      const option = document.createElement('option');
      option.value = model.id;
      option.textContent = model.name || model.id;
      if (model.id === selectedModel) {
        option.selected = true;
      }
      modelInput.appendChild(option);
    });
  }

  async function fetchModels(apiKey) {
    if (fetchAbortController) {
      fetchAbortController.abort();
    }
    fetchAbortController = new AbortController();

    setStatus('Chargement des modèles...', '');

    try {
      const response = await fetch('https://openrouter.ai/api/v1/models', {
        headers: {
          'Authorization': `Bearer ${apiKey}`
        },
        signal: fetchAbortController.signal
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      const models = (data.data || []).map(m => ({
        id: m.id,
        name: m.name || m.id
      })).sort((a, b) => a.name.localeCompare(b.name));

      setModelOptions(models, '');
      setStatus(`${models.length} modèles disponibles.`, 'ok');
    } catch (error) {
      if (error.name === 'AbortError') {
        return;
      }
      setModelOptions([], '');
      setStatus('Erreur lors du chargement des modèles.', 'ko');
    }
  }

  chrome.storage.sync.get(['openrouterApiKey', 'openrouterModel'], (items) => {
    if (items.openrouterApiKey) {
      apiKeyInput.value = items.openrouterApiKey;
      fetchModels(items.openrouterApiKey);
    }
    if (items.openrouterModel) {
      modelInput.value = items.openrouterModel;
    }
  });

  let debounceTimer;
  apiKeyInput.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    const apiKey = apiKeyInput.value.trim();
    if (apiKey.length < 10) {
      setModelOptions([], '');
      return;
    }
    debounceTimer = setTimeout(() => {
      fetchModels(apiKey);
    }, 600);
  });

  saveBtn.addEventListener('click', () => {
    const apiKey = apiKeyInput.value.trim();
    const model = modelInput.value.trim();
    if (!apiKey) {
      setStatus('Veuillez saisir une clé API.', 'ko');
      return;
    }
    if (!model) {
      setStatus('Veuillez sélectionner un modèle.', 'ko');
      return;
    }
    chrome.storage.sync.set({ openrouterApiKey: apiKey, openrouterModel: model }, () => {
      setStatus('Paramètres enregistrés.', 'ok');
    });
  });
})();
