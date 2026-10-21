// Fields without a screen location use text guidance instead of an image viewer.
function renderFieldWithoutImage(f, p, photo) {
  const withoutImage = !f.direct || !photo;
  $('canvas').closest('.viewer').hidden = withoutImage;
  $('inspector').classList.toggle('field-info', withoutImage);
  if (!withoutImage) return false;

  // Clear the previous field's image and controls when navigating between fields.
  $('canvas').replaceChildren();
  $('sceneTabs').replaceChildren();
  $('zoomOpen').hidden = true;
  $('originalLink').hidden = true;
  $('commonNote').hidden = true;
  const example = String(f.example ?? '');
  const exampleHtml = f.field === 'product_url' && /^https?:\/\//i.test(example)
    ? '<a target="_blank" rel="noopener" href="' + esc(example) + '">표본 상품 열기 ↗</a>'
    : esc(example || '등록된 예시가 없습니다.');
  const fact = (title, content) => '<div class="field-info-fact"><dt>' + title + '</dt><dd>' + content + '</dd></div>';
  const notice = f.direct
    ? '화면에서 확인하는 값입니다. 아직 등록된 캡처가 없어 아래 위치 안내를 참고해 주세요.'
    : '쇼핑몰 화면에 직접 표시되지 않는 값입니다. 아래에서 값의 출처와 예시를 확인하세요.';

  $('inspector').innerHTML =
    '<div class="field-info-heading"><span class="field-info-badge">' + (f.direct ? '캡처 미등록' : '화면 미표시 값') + '</span><p>' + notice + '</p></div>' +
    (f.direct && p.blocked ? '<p class="field-info-warning">현재 사이트 화면 미확인 · ' + esc(p.blocked) + '</p>' : '') +
    '<dl class="field-info-grid">' +
    fact(f.direct ? '어디서 찾나요?' : '값의 출처', '<div class="where">' + esc(f.position) + '</div>') +
    fact('값 예시', '<div class="example long">' + exampleHtml + '</div>') +
    fact(f.direct ? '화면의 원문 항목' : '관련 항목', '<div class="origin">' + esc(f.original) + '</div>') +
    fact('수집 구분', esc(f.scope)) +
    '</dl>' +
    '<div class="field-info-note"><strong>확인 방법 · 주의사항</strong><p class="manual-field-note">' + esc(f.note) + '</p></div>';
  return true;
}
