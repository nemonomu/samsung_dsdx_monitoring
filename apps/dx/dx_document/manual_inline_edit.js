// Direct editing uses the same undo stack and explicit server save as the toolbar.
let manualInlineEdit = null;
function manualFinishInlineEdit(cancel = false) {
  const draft = manualInlineEdit;
  if (!draft) return;
  manualInlineEdit = null;
  const value = draft.input.value.trim();
  if (!cancel && value !== draft.original) {
    const f = draft.field;
    const samplePhoto = draft.key === 'example' && !draft.common && draft.photo?.sampleValues?.[f.field] !== undefined ? draft.photo : null;
    pushUndo({kind:'field', target:f, before:cloneValue(f), samplePhoto, beforeSamples:samplePhoto ? cloneValue(samplePhoto.sampleValues) : null});
    f[draft.key] = value;
    f.userEdited = true;
    if (draft.common) f.commonEdited = true;
    if (samplePhoto) samplePhoto.sampleValues[f.field] = value;
    changed();
  }
  draft.node.classList.remove('manual-inline-active');
  draft.node.textContent = cancel ? draft.original : value;
  draft.node.classList.toggle('manual-inline-empty', !draft.node.textContent);
  if (!draft.node.textContent) draft.node.textContent = editing ? '더블클릭하여 입력' : draft.key === 'example' ? '등록된 예시가 없습니다.' : '';
  renderEditorStatus();
}

function manualStartInlineEdit(node, key) {
  if (!editing || saveBusy || manualInlineEdit?.node === node) return;
  manualFinishInlineEdit();
  const f = field(), photo = currentPhoto();
  const original = String(key === 'example' ? manualShownExample(f, photo) ?? '' : manualDisplayField(f, photo)[key] ?? '');
  const input = document.createElement('textarea');
  input.className = 'manual-inline-input';
  input.rows = key === 'position' ? 3 : 2;
  input.maxLength = 20000;
  input.setAttribute('aria-label', key === 'position' ? '어디서 찾나요? 내용 입력' : '값 예시 입력');
  input.value = original;
  const help = document.createElement('small');
  help.className = 'manual-inline-help';
  help.textContent = '다른 곳 클릭 또는 Ctrl+Enter로 적용 · Esc 취소 · 저장으로 보관';
  manualInlineEdit = {node, input, key, field:f, photo, common:S.scope === 'common', original};
  node.classList.add('manual-inline-active');
  node.classList.remove('manual-inline-empty');
  node.removeAttribute('role');
  node.removeAttribute('tabindex');
  node.replaceChildren(input, help);
  input.oninput = () => renderEditorStatus();
  input.onkeydown = event => {
    if (event.isComposing) return;
    if (event.key === 'Escape' || ((event.ctrlKey || event.metaKey) && event.key === 'Enter')) {
      event.preventDefault(); event.stopPropagation();
      manualFinishInlineEdit(event.key === 'Escape');
      node.focus();
    }
  };
  input.onblur = () => manualFinishInlineEdit();
  input.focus();
}

function renderManualInlineControls() {
  const f = field();
  if (!f) return;
  for (const [selector, key, label] of [['.where','position','어디서 찾나요?'],['.example','example','값 예시']]) {
    const node = $('inspector').querySelector(selector);
    if (!node || manualInlineEdit?.node === node) continue;
    node.classList.toggle('manual-inline-editable', editing);
    if (editing) {
      node.tabIndex = 0;
      node.setAttribute('role', 'button');
      node.setAttribute('aria-label', label + ' · 더블클릭 또는 Enter로 수정');
      node.title = '더블클릭하여 수정';
      const value = key === 'example' ? manualShownExample(f,currentPhoto()) : manualDisplayField(f,currentPhoto())[key];
      node.classList.toggle('manual-inline-empty', !value);
      if (!value) node.textContent = '더블클릭하여 입력';
      node.ondblclick = () => manualStartInlineEdit(node,key);
      node.onkeydown = event => {
        if (event.target === node && event.key === 'Enter') {event.preventDefault();manualStartInlineEdit(node,key);}
      };
    } else {
      node.removeAttribute('tabindex'); node.removeAttribute('role'); node.removeAttribute('aria-label'); node.removeAttribute('title');
      node.ondblclick = node.onkeydown = null;
      if (node.classList.contains('manual-inline-empty')) node.textContent = key === 'example' ? '등록된 예시가 없습니다.' : '';
    }
  }
  const badge = $('inspector').querySelector('.field-info-badge');
  if (badge && f.direct) {
    if (editing && badge.tagName !== 'BUTTON') {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'field-info-badge manual-add-capture';
      button.textContent = '캡처 미등록 · 이미지 추가';
      button.onclick = () => {
        if (saveBusy) return;
        manualFinishInlineEdit();
        loadPhotoDraft(-1);
        $('imageEditor').showModal();
        $('addPhoto').click();
      };
      badge.replaceWith(button);
      button.disabled = saveBusy;
    } else if (!editing && badge.tagName === 'BUTTON') {
      const span = document.createElement('span');span.className = 'field-info-badge';span.textContent = '캡처 미등록';badge.replaceWith(span);
    } else if (editing && badge.tagName === 'BUTTON') {
      badge.disabled = saveBusy;
    }
  }
}

const inlineRenderLesson = renderLesson;
renderLesson = function() {manualFinishInlineEdit();inlineRenderLesson();renderManualInlineControls();};
const inlineEditorStatus = renderEditorStatus;
renderEditorStatus = function() {
  inlineEditorStatus();
  if (manualInlineEdit && manualInlineEdit.input.value.trim() !== manualInlineEdit.original && !saveBusy) $('saveGuide').disabled = false;
  renderManualInlineControls();
  renderManualHeaderActions();
};
document.addEventListener('pointerdown', event => {
  if (manualInlineEdit && !manualInlineEdit.node.contains(event.target)) manualFinishInlineEdit();
}, true);
new MutationObserver(records => {
  if (records.some(record => record.target.tagName === 'DIALOG')) renderManualHeaderActions();
}).observe(document.body, {subtree:true, attributes:true, attributeFilter:['open']});
window.addEventListener('beforeunload', event => {
  if (manualInlineEdit && manualInlineEdit.input.value.trim() !== manualInlineEdit.original) {event.preventDefault();event.returnValue = '';}
});
const inlinePhotoUpload = $('photoFile').onchange;
$('photoFile').onchange = async event => {
  await inlinePhotoUpload(event);
  if (event.target.files?.length && workingPhoto && !$('imageError').textContent && !workingPhoto.boxes.length) {
    drawing = true; renderImageStage();
    showToast('이미지에서 값을 둘러싸도록 드래그해 번호 박스를 그려 주세요.');
  }
};
