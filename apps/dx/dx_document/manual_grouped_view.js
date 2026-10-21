// Keep the original dataset objects as the source for viewing, editing and saving.
// S.c is always a real product; S.scope controls only which fields are listed.
const manualCategoryCodes = {tv: 'TV', ref: 'REF', ldy: 'LDY', ldy_dryer: 'DRYER', dryer: 'DRYER', hhp: 'HHP', all: '공통'};
const manualDatasets = () => D.datasets.filter(dataset => dataset.retailer === S.r && dataset.category !== 'all');
const manualAllDatasets = () => D.datasets.filter(dataset => dataset.retailer === S.r);
const manualScopedFields = () => manualFieldsForScope(manualAllDatasets(), S.c, S.scope);
const manualCategoryLabel = category => manualCategoryCodes[category] || shortCat[category] || category;
S.scope = 'common';
S.field = 'retailer_sku_name';

const manualHero = document.querySelector('.hero');
manualHero.after($('categoryNav'));
$('categoryNav').classList.add('manual-scope-tabs');
$('categoryNav').setAttribute('aria-label', '컬럼 범위');
const manualScopeNote = document.createElement('p');
manualScopeNote.id = 'manualScopeNote';
$('categoryNav').after(manualScopeNote);
manualHero.querySelector('p').textContent = '공통 기준은 한곳에서, 제품군별 확인 방법은 따로 확인하세요.';
const manualScopeBadge = document.createElement('span');
manualScopeBadge.className = 'manual-scope-badge';
document.querySelector('.lessonhead-left').append(manualScopeBadge);
const manualExample = document.createElement('section');
manualExample.id = 'manualExample';
manualExample.className = 'manual-example';
manualExample.innerHTML = '<header class="manual-example-head" id="manualExampleHead"></header><div class="manual-example-body"></div>';
document.querySelector('.lessonhead').after(manualExample);
manualExample.lastElementChild.append(document.querySelector('.viewer'), $('inspector'));

function normalizeManualScope() {
  const datasets = manualDatasets();
  if (!datasets.some(dataset => dataset.category === S.c)) S.c = datasets[0].category;
  if (S.scope !== 'common') S.scope = S.c;
  const fields = manualScopedFields();
  if (!fields.some(f => f.field === S.field)) {
    S.field = (fields.find(f => f.field === 'retailer_sku_name') || fields[0])?.field || '';
    S.photo = 0;
  }
}

const manualBaseNavigation = navigation;
navigation = function() {
  manualBaseNavigation();
  renderManualCountryHeader();
  const datasets = manualDatasets(), common = manualCommonKeys(manualAllDatasets());
  const scopes = ['common', ...datasets.map(dataset => dataset.category)];
  $('categoryNav').innerHTML = scopes.map(scope => {
    const count = scope === 'common' ? common.size : manualFieldsForScope(manualAllDatasets(), scope, scope).length;
    return '<button class="category ' + (S.scope === scope ? 'on' : '') + '" data-scope="' + esc(scope) + '" aria-pressed="' + (S.scope === scope) + '">' +
      (scope === 'common' ? '공통 컬럼' : esc(manualCategoryLabel(scope))) + '<span class="manual-tab-count">' + count + '</span></button>';
  }).join('');
  $('categoryNav').querySelectorAll('button').forEach(button => button.onclick = () => {
    S.scope = button.dataset.scope;
    if (S.scope !== 'common') S.c = S.scope;
    S.field = '';
    S.q = '';
    $('fieldSearch').value = '';
    S.photo = 0;
    render();
  });
};

const manualBaseRender = render;
render = function() {
  normalizeManualScope();
  manualBaseRender();
  const common = S.scope === 'common';
  $('heading').innerHTML = esc(profile().name) + '<span>/</span>' + (common ? '공통 컬럼' : esc(shortCat[S.c]));
  $('fieldCount').textContent = manualScopedFields().length + '개';
  document.querySelector('.fieldpane-head h2').firstChild.textContent = common ? '공통 컬럼 ' : manualCategoryLabel(S.c) + ' 제품군별 ';
  $('manualScopeNote').textContent = common
    ? '공통 컬럼의 설명과 이미지를 한곳에서 관리합니다. 여러 화면은 캡처 선택으로 확인하세요.'
    : manualCategoryLabel(S.c) + '의 제품군별 컬럼입니다. 공통 컬럼은 공통 탭에서 확인하세요.';
  $('routeSummary').insertAdjacentHTML('afterbegin', '<strong class="manual-route-product">' + esc(manualCategoryLabel(S.c)) + ' · </strong>');
};

const manualBaseSetField = setField;
setField = function(key) {
  // The all-fields table can jump to a field outside the current scope.
  if (!manualScopedFields().some(f => f.field === key)) {
    S.scope = manualCommonKeys(manualAllDatasets()).has(key) ? 'common' : S.c;
    S.field = key;
    S.photo = 0;
    render();
  } else manualBaseSetField(key);
};

const manualBaseRenderLesson = renderLesson;
renderLesson = function() {
  const fields = manualScopedFields(), common = S.scope === 'common';
  manualExample.hidden = !fields.length;
  manualScopeBadge.textContent = common ? '공통 컬럼' : manualCategoryLabel(S.c) + ' 제품군별';
  if (!fields.length) {
    $('lessonTitle').textContent = '등록된 컬럼이 없습니다.';
    $('lessonCode').textContent = '편집 모드에서 컬럼을 추가해 주세요.';
    $('lessonNumber').textContent = '–';
    $('prevField').disabled = $('nextField').disabled = true;
    renderEditorStatus();
    return;
  }
  manualBaseRenderLesson();
  const f = field(), index = fields.indexOf(f);
  $('prevField').disabled = index <= 0;
  $('nextField').disabled = index >= fields.length - 1;
  if (!common) {
    const appliesTo = manualDatasets().filter(dataset => dataset.fields.some(candidate => candidate.field === f.field));
    manualScopeBadge.textContent = appliesTo.length > 1 ? appliesTo.map(dataset => manualCategoryLabel(dataset.category)).join(' · ') + ' 적용' : manualCategoryLabel(S.c) + ' 전용';
  }
  $('manualExampleHead').innerHTML = '<h3>' + (common ? '확인 방법 · 이미지' : esc(shortCat[S.c]) + ' 확인 방법') + '</h3><p>같은 컬럼의 여러 화면은 캡처 선택에서 바꿔 볼 수 있습니다.</p>';
  const photo = currentPhoto();
  if (photo && common) $('photoSource').insertAdjacentHTML('afterbegin', '<strong>' + esc(photo.category === 'all' ? '공통' : manualCategoryLabel(photo.category)) + ' 캡처</strong> · ');

};

function manualStepField(direction) {
  const fields = manualScopedFields(), index = fields.findIndex(f => f.field === S.field);
  const target = fields[index + direction];
  if (target) setField(target.field);
}
$('prevField').onclick = () => manualStepField(-1);
$('nextField').onclick = () => manualStepField(1);

const manualBaseEditorStatus = renderEditorStatus;
renderEditorStatus = function() {
  manualBaseEditorStatus();
  if ($('manualEditHint')) $('manualEditHint').hidden = !editing;
  $('editText').textContent = (S.scope === 'common' ? '공통' : manualCategoryLabel(S.c)) + ' · 문구 수정';
  $('editImage').textContent = (S.scope === 'common' ? '공통' : manualCategoryLabel(S.c)) + ' · 이미지 추가·수정';
  if (!manualScopedFields().length) $('editText').disabled = $('editImage').disabled = true;
};
