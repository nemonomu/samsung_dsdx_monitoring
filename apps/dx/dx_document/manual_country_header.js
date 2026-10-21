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
