// Additional title/content pairs belong to the selected column, independently of its original guidance.
const manualDetailEditor = document.createElement('dialog');
manualDetailEditor.id = 'manualDetailEditor';
manualDetailEditor.className = 'editdialog manual-detail-editor';
manualDetailEditor.setAttribute('aria-labelledby', 'manualDetailHeading');
manualDetailEditor.innerHTML = '<form id="manualDetailForm"><div class="dialoghead"><h2 id="manualDetailHeading">상세내용 추가</h2><button type="button" class="close" aria-label="닫기">×</button></div><div class="dialogbody"><label>제목<input id="manualDetailTitle" required maxlength="150" placeholder="예: 옵션 선택 시 주의사항"></label><label>상세내용<textarea id="manualDetailContent" required maxlength="20000" rows="6" placeholder="추가로 안내할 내용을 입력하세요."></textarea></label><p>기존 ‘어디서 찾나요?’ 내용 아래에 추가됩니다. 적용 후 저장을 눌러 보관하세요.</p><p id="manualDetailError" class="formerror" role="alert"></p></div><div class="editactions"><button type="button" id="manualDetailCancel">취소</button><button type="submit" class="primary">적용</button></div></form>';
document.body.append(manualDetailEditor);
manualDetailEditor.querySelector('.close').onclick = $('manualDetailCancel').onclick = () => manualDetailEditor.close();
let manualDetailTarget = null;

function openManualDetail(index = -1) {
  if (!editing || saveBusy) return;
  manualFinishInlineEdit();
  const f = field(), details = f.details || [];
  if (index < 0 && details.length >= 20) {showToast('상세내용은 최대 20개까지 추가할 수 있습니다.');return;}
  manualDetailTarget = {field:f, index};
  $('manualDetailHeading').textContent = index < 0 ? '상세내용 추가' : '상세내용 수정';
  $('manualDetailTitle').value = details[index]?.title || '';
  $('manualDetailContent').value = details[index]?.content || '';
  $('manualDetailError').textContent = '';
  manualDetailEditor.showModal();
  $('manualDetailTitle').focus();
}
$('manualDetailForm').onsubmit = event => {
  event.preventDefault();
  const title = $('manualDetailTitle').value.trim(), content = $('manualDetailContent').value.trim();
  if (!title || !content) {$('manualDetailError').textContent = '제목과 상세내용을 모두 입력하세요.';return;}
  const {field:f, index} = manualDetailTarget;
  const details = f.details || [];
  if (index < 0 && details.length >= 20) return;
  pushUndo({kind:'field', target:f, before:cloneValue(f)});
  f.details = [...details];
  if (index < 0) f.details.push({title, content});
  else f.details[index] = {title, content};
  f.userEdited = true;
  changed(); renderLesson(); manualDetailEditor.close();
  showToast('상세내용을 적용했습니다. 저장을 눌러 보관하세요.');
};

function renderManualDetails() {
  const f = field(), where = $('inspector').querySelector('.where');
  const previous = $('manualDetails');
  const signature = JSON.stringify([editing, saveBusy, f?.details || []]);
  if (previous && previous.previousElementSibling === where && previous.manualField === f && previous.manualSignature === signature) return;
  previous?.remove();
  if (!f || !where || (!editing && !f.details?.length)) return;
  const container = document.createElement('div');
  container.manualField = f;
  container.manualSignature = signature;
  container.id = 'manualDetails';
  container.className = 'manual-details';
  (f.details || []).forEach((detail, index) => {
    const article = document.createElement('section');
    article.className = 'manual-detail-item';
    const heading = document.createElement('h4');heading.textContent = detail.title;
    const body = document.createElement('p');body.textContent = detail.content;
    article.append(heading, body);
    if (editing) {
      const edit = document.createElement('button');
      edit.type = 'button';edit.className = 'manual-detail-edit';edit.textContent = '수정';
      edit.setAttribute('aria-label', detail.title + ' 상세내용 수정');edit.disabled = saveBusy;
      edit.onclick = () => openManualDetail(index);
      heading.ondblclick = body.ondblclick = () => openManualDetail(index);
      article.append(edit);
    }
    container.append(article);
  });
  if (editing) {
    const add = document.createElement('button');
    add.type = 'button';add.className = 'manual-add-button';add.textContent = '＋ 상세내용 추가';
    add.disabled = saveBusy || (f.details?.length || 0) >= 20;
    add.onclick = () => openManualDetail();container.append(add);
  }
  where.after(container);
}
const detailsRenderLesson = renderLesson;
renderLesson = function() {detailsRenderLesson();renderManualDetails();};
const detailsEditorStatus = renderEditorStatus;
renderEditorStatus = function() {detailsEditorStatus();renderManualDetails();};
