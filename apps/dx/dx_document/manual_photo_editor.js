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

function renderManualCapture(photo, f) {
  const annotated = photo.boxes.some(box => box.fields.includes(f.field));
  const full = !annotated || S.view === 'full';
  if (!annotated) $('sceneTabs').innerHTML = '<span class="scene-tab on">전체 화면</span>';
  const caption = !annotated ? '등록한 전체 캡처입니다.' : full
    ? '이미지 전체에서 <strong>' + f.n + '번 박스</strong>의 위치를 확인하세요.'
    : '같은 캡처의 <strong>' + f.n + '번 박스 주변</strong>을 확대했습니다.';
  $('canvas').dataset.view = full ? 'full' : 'data';
  $('canvas').innerHTML = '<div class="view-caption">' + caption + '</div>' + svg(photo, full);
  $('originalLink').href = photoSrc(photo);
  $('photoSource').innerHTML = esc(photo.stage) + (photo.url
    ? ' · <a href="' + esc(photo.url) + '" target="_blank" rel="noopener">출처 페이지 ↗</a>'
    : ' · 제공된 캡처') + '<br>' + esc(photo.region) + ' · ' + esc(photo.date);
}

function renderCaptureNavigation(count) {
  const canvas = $('canvas');
  const image = canvas.querySelector(':scope > svg');
  const showNavigation = count > 1 && image !== null;
  canvas.classList.toggle('manual-capture-carousel', showNavigation);
  if (!showNavigation) return;
  const arrow = (id, step, label, direction, disabled) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.id = id;
    button.className = 'manual-capture-arrow';
    button.setAttribute('aria-label', label);
    button.innerHTML = icon(direction);
    button.disabled = disabled;
    button.onclick = () => {
      S.photo += step;
      renderLesson();
      const sameButton = $(id);
      const focus = sameButton.disabled ? $(id === 'prevPhoto' ? 'nextPhoto' : 'prevPhoto') : sameButton;
      focus.focus({preventScroll: true});
    };
    return button;
  };
  const position = document.createElement('div');
  position.id = 'capturePosition';
  position.setAttribute('role', 'status');
  position.innerHTML = '<span class="manual-capture-count">' + (S.photo + 1) + ' / ' + count + '</span>' +
    Array.from({length: count}, (_, i) => '<span aria-hidden="true" class="manual-capture-dot' +
      (i === S.photo ? ' is-current' : '') + '"></span>').join('');
  image.before(arrow('prevPhoto', -1, '이전 캡처', 'left', S.photo === 0));
  image.after(arrow('nextPhoto', 1, '다음 캡처', 'right', S.photo === count - 1), position);
}

renderLesson = function() {
  manualPhotoRenderLesson();
  const p = currentPhoto();
  const candidates = p ? shownPhotos() : [];
  renderCaptureNavigation(candidates.length);
  if (!p) return;
  const pager = $('photoPager');
  pager.innerHTML = '<span id="captureDescription">' + (S.photo === 0 ? '대표 · ' : '') +
    esc((S.scope === 'common' ? manualCategoryLabel(p.category) + ' · ' : '') + p.stage + ' · ' + p.date) + '</span>';
  const button = document.createElement('button');
  button.type = 'button';
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
  pager.append(button);
};
// Keep capture details and the representative action above a tall screenshot.
$('canvas').before($('photoPager'));
$('replacePhoto').textContent = '현재 이미지 교체';
$('replacePhoto').title = '선택한 캡처를 교체합니다. 저장 전 이미지는 수정 이력에 남습니다.';
$('addPhoto').textContent = '별도 캡처 추가';
$('addPhoto').title = '기존 캡처를 유지하고 이 컬럼의 대표 캡처를 추가합니다.';
$('applyImage').textContent = '적용 후 저장';

const manualClipboardHelp = document.createElement('small');
manualClipboardHelp.textContent = 'Ctrl+V로 캡처 붙여넣기';
$('photoFile').before(manualClipboardHelp);
const manualImageTypes = ['image/png', 'image/jpeg', 'image/webp'];
let manualImageRead = null;

async function loadManualImage(file, add, fromClipboard = false) {
  const editor = $('imageEditor');
  if (!editor.open || saveBusy) return;
  if (!manualImageTypes.includes(file.type)) {
    $('imageError').textContent = 'PNG, JPG, WEBP 이미지를 선택하세요.';
    return;
  }
  if (file.size > 15 * 1024 * 1024) {
    $('imageError').textContent = '15MB 이하의 이미지를 선택하세요.';
    return;
  }
  const reading = {};
  const previousDraft = workingPhoto;
  manualImageRead = reading;
  $('applyImage').disabled = true;
  $('imageError').textContent = '';
  try {
    const src = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    const image = new Image();
    image.src = src;
    await image.decode();
    if (manualImageRead !== reading || !editor.open || workingPhoto !== previousDraft) return;
    photoMetadataToDraft();
    if (add || !workingPhoto) {
      editingPhotoIndex = -1;
      workingPhoto = {retailer:S.r, category:S.scope === 'common' ? 'all' : S.c,
        stage:'상세', region:profile().region, note:'사용자가 추가한 이미지입니다.',
        name:'user_photo_' + Date.now(), url:'', date:today(), boxes:[]};
      if (fromClipboard) workingPhoto.captureField = S.field;
    }
    Object.assign(workingPhoto, {customImage:src, width:image.naturalWidth, height:image.naturalHeight, boxes:[]});
    selectedBox = -1;
    drawing = !fromClipboard;
    drawStart = null;
    renderPhotoEditor();
    showToast(fromClipboard ? '캡처를 붙여넣었습니다. 바로 저장하거나 번호 박스를 그릴 수 있습니다.'
      : '이미지에서 값을 둘러싸도록 드래그해 번호 박스를 그려 주세요.');
  } catch {
    if (manualImageRead === reading) $('imageError').textContent = '이미지를 읽지 못했습니다. 다른 이미지를 사용해주세요.';
  } finally {
    if (manualImageRead === reading) {
      manualImageRead = null;
      $('applyImage').disabled = saveBusy;
    }
  }
}

$('photoFile').onchange = event => {
  const file = event.target.files?.[0];
  if (file) void loadManualImage(file, newUpload);
};
document.addEventListener('paste', event => {
  if (!$('imageEditor').open || saveBusy || event.defaultPrevented) return;
  const clipboard = event.clipboardData;
  const file = Array.from(clipboard?.files || []).find(item => item.type.startsWith('image/'))
    || Array.from(clipboard?.items || []).find(item => item.kind === 'file' && item.type.startsWith('image/'))?.getAsFile();
  if (!file) return;
  event.preventDefault();
  void loadManualImage(file, true, true);
});
$('imageEditor').addEventListener('close', () => {
  manualImageRead = null;
  $('applyImage').disabled = saveBusy;
});

const manualPhotoEditorStatus = renderEditorStatus;
renderEditorStatus = function() {
  manualPhotoEditorStatus();
  $('applyImage').disabled = saveBusy || manualImageRead !== null;
  const button = $('manualPrimaryPhoto');
  if (button) {
    button.hidden = !editing;
    button.disabled = saveBusy || currentPhoto() === shownPhotos()[0];
  }
};

const manualPhotoApply = $('applyImage').onclick;
$('applyImage').onclick = async () => {
  if (saveBusy || manualImageRead !== null) return;
  const addingPastedCapture = editingPhotoIndex < 0 && workingPhoto?.captureField;
  manualInitializePhotoPreferences(D.photos);
  manualPhotoApply();
  if ($('imageEditor').open) return; // Validation failed; keep the draft.
  if (!addingPastedCapture) {
    const p = currentPhoto();
    if (p) manualMakePrimary(D.photos, p, S);
    S.photo = 0;
  }
  renderLesson();
  await saveManual();
};
