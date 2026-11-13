// All countries use the same selection, replacement and save behavior.
let manualInitializedPhotos = null;
photos = function() {
  if (manualInitializedPhotos !== D.photos) {
    manualInitializePhotoPreferences(D.photos);
    manualInitializedPhotos = D.photos;
  }
  return manualSortPhotos(manualPhotoCandidates(D.photos, S), S);
};

const manualPhotoRenderLesson = renderLesson;
renderLesson = function() {
  manualPhotoRenderLesson();
  const p = currentPhoto();
  if (!p) return;
  const candidates = shownPhotos();
  const select = $('captureSelect');
  if (select) for (const option of select.options) {
    const item = candidates[Number(option.value)];
    option.textContent = (item === candidates[0] ? '대표 · ' : '') + option.textContent + ' · ' + item.date;
  }
  const button = document.createElement('button');
  button.id = 'manualPrimaryPhoto';
  button.textContent = p === candidates[0] ? '대표 캡처' : '이 캡처를 대표로 설정';
  button.hidden = !editing;
  button.disabled = saveBusy || p === candidates[0];
  button.onclick = async () => {
    if (saveBusy) return;
    pushUndo({kind:'photo', target:p, before:cloneValue(p)});
    manualMakePrimary(D.photos, p, S);
    S.photo = 0;
    changed();
    renderLesson();
    await saveManual();
  };
  $('photoPager').append(button);
};
// Keep the capture chooser visible before a tall screenshot.
$('canvas').before($('photoPager'));
$('replacePhoto').textContent = '현재 이미지 교체';
$('replacePhoto').title = '선택한 캡처를 교체합니다. 저장 전 이미지는 수정 이력에 남습니다.';
$('addPhoto').textContent = '별도 캡처 추가';
$('addPhoto').title = '기존 캡처를 유지하고 이 컬럼의 대표 캡처를 추가합니다.';
$('applyImage').textContent = '적용 후 저장';
const manualPhotoEditorStatus = renderEditorStatus;
renderEditorStatus = function() {
  manualPhotoEditorStatus();
  $('applyImage').disabled = saveBusy;
  const button = $('manualPrimaryPhoto');
  if (button) {
    button.hidden = !editing;
    button.disabled = saveBusy || currentPhoto() === shownPhotos()[0];
  }
};

const manualPhotoApply = $('applyImage').onclick;
$('applyImage').onclick = async () => {
  if (saveBusy) return;
  manualInitializePhotoPreferences(D.photos);
  manualPhotoApply();
  if ($('imageEditor').open) return; // Validation failed; keep the draft.
  const p = currentPhoto();
  if (p) manualMakePrimary(D.photos, p, S);
  S.photo = 0;
  renderLesson();
  await saveManual();
};
