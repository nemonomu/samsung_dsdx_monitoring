// Mirror the existing country controls into the same-origin Document header.
// Keep the editor alive when switching countries so unsaved work stays intact.
function renderManualCountryHeader() {
  let header;
  try {
    if (window.frameElement?.id !== 'manualGuideFrame') return;
    header = window.parent.document.getElementById('manualCountryNav');
  } catch {
    return; // A standalone or cross-origin guide keeps its own country navigation.
  }
  if (!header) return;
  const focusedCountry = header.contains(header.ownerDocument.activeElement)
    ? header.ownerDocument.activeElement.dataset.country : null;
  const buttons = [...$('countryNav').querySelectorAll('button')].map(source => {
    const button = source.cloneNode(true);
    button.type = 'button';
    button.onclick = () => source.click();
    return button;
  });
  header.replaceChildren(...buttons);
  header.setAttribute('aria-busy', 'false');
  if (focusedCountry) buttons.find(button => button.dataset.country === focusedCountry)?.focus();
  document.body.classList.add('manual-country-header-hosted');
  $('retailerNav').setAttribute('aria-label', S.country + ' 쇼핑몰 선택');
  if (!$('manualRetailerLabel')) {
    const label = document.createElement('span');
    label.id = 'manualRetailerLabel';
    label.className = 'manual-retailer-label';
    label.textContent = '쇼핑몰';
    $('retailerNav').before(label);
  }
}

function renderManualHeaderActions() {
  let parent;
  try {
    if (window.frameElement?.id !== 'manualGuideFrame') return;
    parent = window.parent.document;
  } catch { return; }
  const actions = parent.getElementById('manualHeaderActions');
  if (!actions) return;
  if (!actions.dataset.shortcutsReady) {
    actions.dataset.shortcutsReady = 'true';
    parent.addEventListener('keydown', event => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        void saveManual();
      }
    });
  }
  actions.hidden = false;
  const edit = parent.getElementById('manualHeaderEdit');
  const save = parent.getElementById('manualHeaderSave');
  const status = parent.getElementById('manualHeaderStatus');
  const modalOpen = !!document.querySelector('dialog[open]');
  edit.textContent = editing ? '편집 종료' : '편집 모드';
  edit.setAttribute('aria-pressed', String(editing));
  edit.disabled = saveBusy || modalOpen;
  edit.onclick = () => {manualFinishInlineEdit(); $('editModeToggle').click();};
  save.hidden = !editing && revision === downloadedRevision;
  save.disabled = $('saveGuide').disabled || modalOpen;
  save.textContent = saveBusy ? '저장 중…' : '저장';
  save.onclick = () => {manualFinishInlineEdit(); $('saveGuide').click();};
  const dirty = revision !== downloadedRevision || !!manualInlineEdit;
  status.textContent = saveBusy ? '저장 중' : dirty ? '저장하지 않은 변경' : editing ? '저장됨' : '';
  status.classList.toggle('dirty', dirty);
  $('editModeToggle').hidden = true;
  parent.querySelectorAll('#manualCountryNav button').forEach(button => button.disabled = modalOpen || saveBusy);
}
