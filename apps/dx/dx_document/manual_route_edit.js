// Route guidance is shared by products within one country/retailer, separately per mode.
function manualRouteText(p, mode) {
  return p.routeNotes?.[mode] ?? ((mode === 'main' ? p.mainSort : p.bsrSort) || '상품 순서와 확인 위치는 방문 방법을 참고하세요.');
}
function renderManualRoute() {
  const node = $('routeSummary');
  node.innerHTML = '<strong>' + esc(S.mode.toUpperCase()) + ' 목록</strong> · <span class="manual-route-text">' + esc(manualRouteText(profile(), S.mode)) + '</span>';
  node.classList.toggle('manual-inline-editable', editing);
  if (editing) {
    node.tabIndex = 0;
    node.setAttribute('role', 'button');
    node.setAttribute('aria-label', S.mode.toUpperCase() + ' 안내 문구 · 더블클릭 또는 Enter로 수정');
    node.title = '더블클릭하여 안내 문구 수정';
    node.ondblclick = openManualRouteEditor;
    node.onkeydown = event => {if (event.key === 'Enter') {event.preventDefault();openManualRouteEditor();}};
  } else {
    for (const attr of ['tabindex','role','aria-label','title']) node.removeAttribute(attr);
    node.ondblclick = node.onkeydown = null;
  }
}
const manualRouteEditor = document.createElement('dialog');
manualRouteEditor.id = 'manualRouteEditor';
manualRouteEditor.className = 'editdialog manual-detail-editor';
manualRouteEditor.setAttribute('aria-labelledby', 'manualRouteHeading');
manualRouteEditor.innerHTML = '<form id="manualRouteForm"><div class="dialoghead"><h2 id="manualRouteHeading">안내 문구 수정</h2><button type="button" class="close" aria-label="닫기">×</button></div><div class="dialogbody"><label>안내 문구<textarea id="manualRouteText" maxlength="20000" rows="5"></textarea></label><p>선택한 쇼핑몰의 제품군에 공통으로 적용됩니다. MAIN과 BSR 문구는 각각 저장됩니다.</p></div><div class="editactions"><button type="button" id="manualRouteCancel">취소</button><button type="submit" class="primary">적용</button></div></form>';
document.body.append(manualRouteEditor);
manualRouteEditor.querySelector('.close').onclick = $('manualRouteCancel').onclick = () => manualRouteEditor.close();
let manualRouteTarget = null;
function openManualRouteEditor() {
  if (!editing || saveBusy) return;
  manualFinishInlineEdit();
  manualRouteTarget = {profile:profile(), mode:S.mode};
  $('manualRouteHeading').textContent = profile().name + ' · ' + S.mode.toUpperCase() + ' 안내 문구 수정';
  $('manualRouteText').value = manualRouteText(profile(), S.mode);
  manualRouteEditor.showModal();
  $('manualRouteText').focus();
}
$('manualRouteForm').onsubmit = event => {
  event.preventDefault();
  const {profile:p, mode} = manualRouteTarget, value = $('manualRouteText').value.trim();
  if (value !== manualRouteText(p, mode)) {
    pushUndo({kind:'field', target:p, before:cloneValue(p)});
    p.routeNotes = {...p.routeNotes, [mode]:value};
    changed();
  }
  manualRouteEditor.close();
  renderManualRoute();
};
const routeEditorStatus = renderEditorStatus;
renderEditorStatus = function() {routeEditorStatus();renderManualRoute();};
