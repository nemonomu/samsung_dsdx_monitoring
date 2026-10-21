// Expandable manual-only structure. Collection configuration is never written here.
function manualCurrentDataset() {
  const category = S.scope === 'common' ? 'all' : S.c;
  return D.datasets.find(d => d.retailer === S.r && d.category === category)
    || D.datasets.find(d => d.retailer === S.r && d.category === S.c)
    || D.datasets.find(d => d.retailer === S.r && d.category !== 'all')
    || D.datasets.find(d => d.category !== 'all');
}
function manualEntry() {
  const p = profile();
  if (S.scope === 'common') return p.homepage || p.mainBase || '';
  const base = p.mainBase || '';
  const query = p.queries?.[S.c] || '';
  return S.mode === 'main' || p.bsrSearch ? (p.searchUI ? base : base + encodeURIComponent(query)) : (p.bsr?.[S.c] || p.homepage || '');
}
function manualAnnotationFields() {
  // Keep every existing box link, including mixed common/product captures.
  const fields = new Map(ds().fields.map(f => [f.field, f]));
  for (const row of manualAllDatasets()) for (const f of row.fields) if (!fields.has(f.field)) fields.set(f.field, f);
  return [...fields.values()].filter(f => !manualExcludedFields.has(f.field));
}
function manualDisplayField(f, photo) {
  if (S.scope !== 'common' || f.commonEdited || !photo) return f;
  const variant = f.legacyVariants?.find(v => v.category === photo.category);
  return variant ? {...f, ...variant} : f;
}
function manualShownExample(f, photo) {
  if (S.scope === 'common' && f.commonEdited) return f.example;
  return photo?.sampleValues?.[f.field] ?? manualDisplayField(f, photo).example;
}
photos = function() {
  if (!S.field) return [];
  return D.photos.filter(p => p.retailer === S.r &&
    (S.scope === 'common' || p.category === S.c || p.category === 'all') &&
    p.boxes.some(b => b.fields.includes(S.field))).sort((a,b) => Number(!!a.commonExample)-Number(!!b.commonExample) || score(b)-score(a));
};
availableEditorPhotos = function() {
  return D.photos.map((p,i)=>({p,i})).filter(({p})=>p.retailer===S.r &&
    (S.scope==='common' || p.category===S.c || p.category==='all'));
};

function renderManualLegacyNotes(f) {
  if (!f.legacyVariants?.length) return;
  const unique = new Map();
  for (const v of f.legacyVariants) {
    const signature = JSON.stringify([v.page,v.position,v.original,v.example,v.note]);
    if (!unique.has(signature)) unique.set(signature, {value:v, categories:[]});
    unique.get(signature).categories.push(manualCategoryLabel(v.category));
  }
  if (unique.size < 2) return;
  const details = document.createElement('details');
  details.className = 'manual-legacy-notes';
  details.innerHTML = '<summary>기존 설명 참고 · ' + unique.size + '개</summary><p>기존에 등록된 서로 다른 설명을 보존했습니다. 공통 본문은 문구 수정에서 작성하세요.</p>' +
    [...unique.values()].map(({value:v,categories})=>'<article><strong>'+esc(categories.join(' · '))+'</strong><p>'+esc(v.position)+'</p><p>'+esc(v.original)+'</p><p>'+esc(v.example)+'</p><p>'+esc(v.note)+'</p></article>').join('');
  $('inspector').append(details);
}

renderTable = function() {
  const q=$('tableSearch').value.toLowerCase();
  const all=manualAllDatasets();
  const entries=[...manualFieldsForScope(all,S.c,'common').map(f=>({f,scope:'common'})),
    ...manualDatasets().flatMap(d=>manualFieldsForScope(all,d.category,d.category).map(f=>({f,scope:d.category})))];
  $('tableTitle').textContent=profile().name+' 전체 '+entries.length+'개 컬럼';
  $('tableRows').innerHTML=entries.filter(({f})=>!q||[f.field,f.label,f.position].join(' ').toLowerCase().includes(q)).map(({f,scope})=>
    '<tr><td><button class="tablelink" data-jump="'+esc(f.field)+'" data-scope="'+esc(scope)+'">'+f.n+' →</button><br>'+esc(scope==='common'?'공통':manualCategoryLabel(scope))+'</td><td><code>'+esc(f.field)+'</code><br>'+esc(f.label)+'</td><td>'+esc(f.scope)+'</td><td>'+esc(f.page)+'<br>'+esc(f.position)+'<small>'+esc(f.original)+'</small></td><td>'+esc(f.example)+'<small>'+esc(f.note)+'</small></td></tr>').join('');
  $('tableRows').querySelectorAll('[data-jump]').forEach(b=>b.onclick=()=>{
    S.scope=b.dataset.scope;if(S.scope!=='common')S.c=S.scope;S.field=b.dataset.jump;S.photo=0;
    S.q='';$('fieldSearch').value='';$('tableDialog').close();render();
  });
};
routeInfo = function() {
  const p=profile(),link=entry();
  openInfo(p.name+' 방문 방법','<h3>MAIN · BSR 목록</h3><p>MAIN은 검색 목록, BSR은 설정된 카테고리·정렬 목록에서의 상품 순서입니다.</p><p>'+esc(p.mainSort||'MAIN 방문 기준을 등록해 주세요.')+'</p><p>'+esc(p.bsrSort||'BSR 방문 기준을 등록해 주세요.')+'</p>'+
    (link?'<p><a href="'+esc(link)+'" target="_blank" rel="noopener">쇼핑몰 열기 ↗</a></p>':'<p>등록된 쇼핑몰 주소가 없습니다.</p>')+'<p>'+esc(p.summary)+'</p><p>'+esc(p.warning)+'</p>');
};
$('routeDetails').onclick=routeInfo;
const expandedRender=render;
render=function(){
  if (!D.profiles[S.r]) {S.r=Object.keys(D.profiles)[0];S.country=D.profiles[S.r].country;}
  expandedRender();
  $('entryLink').hidden=!/^https?:\/\//i.test(entry());
  $('routeSummary').innerHTML='<strong>'+esc(S.mode.toUpperCase())+' 목록</strong> · '+esc((S.mode==='main'?profile().mainSort:profile().bsrSort)||'상품 순서와 확인 위치는 방문 방법을 참고하세요.');
  if(!manualScopedFields().length&&!S.q)$('fieldList').innerHTML='<div class="notfound">등록된 컬럼이 없습니다.<br>편집 모드에서 컬럼을 추가하세요.</div>';
};

const addRetailer=document.createElement('button');
addRetailer.id='manualAddRetailer';addRetailer.className='manual-add-button';addRetailer.textContent='＋ 쇼핑몰 추가';
$('retailerNav').after(addRetailer);
const addColumn=document.createElement('button');
addColumn.id='manualAddColumn';addColumn.className='manual-add-button';addColumn.textContent='＋ 컬럼 추가';
document.querySelector('.fieldpane-head').append(addColumn);
const structureDialog=document.createElement('dialog');
structureDialog.className='editdialog manual-structure-dialog';structureDialog.id='manualStructureDialog';
structureDialog.innerHTML='<form id="manualStructureForm"><div class="dialoghead"><h2 id="manualStructureTitle"></h2><button type="button" id="manualStructureClose" class="close" aria-label="닫기">×</button></div><div class="dialogbody" id="manualStructureBody"></div><p id="manualStructureError" class="formerror" role="alert"></p><div class="manual-structure-actions"><button type="submit" class="primary">추가</button></div></form>';
document.body.append(structureDialog);
$('manualStructureClose').onclick=()=>structureDialog.close();
let manualStructureAction=null;
function manualOpenStructure(title,html,action){
  $('manualStructureTitle').textContent=title;$('manualStructureBody').innerHTML=html;$('manualStructureError').textContent='';manualStructureAction=action;structureDialog.showModal();
}
function structureUndo(){pushUndo({kind:'structure',before:cloneValue(D),state:cloneValue(S)});}
$('manualStructureForm').onsubmit=event=>{
  event.preventDefault();
  try{manualStructureAction();changed();structureDialog.close();render();showToast('추가했습니다. 저장을 눌러 보관하세요.');}
  catch(error){$('manualStructureError').textContent=error.message;}
};
addRetailer.onclick=()=>{
  const country=S.country,prefix=S.r.split('/')[0];
  manualOpenStructure(country+' 쇼핑몰 추가',
    '<p>매뉴얼에 새 쇼핑몰을 등록합니다. 실제 수집 설정은 변경하지 않습니다.</p><label>쇼핑몰 이름<input id="manualRetailerName" required maxlength="100" placeholder="쇼핑몰 이름"></label><label>홈페이지 주소<input id="manualRetailerUrl" type="url" placeholder="https://"></label><fieldset><legend>제품군</legend>'+['tv','ref','ldy','ldy_dryer','hhp'].map(c=>'<label class="manual-check"><input type="checkbox" name="manualProducts" value="'+c+'" '+(c!=='hhp'?'checked':'')+'>'+manualCategoryLabel(c)+'</label>').join('')+'</fieldset>',()=>{
      const name=$('manualRetailerName').value.trim(),url=$('manualRetailerUrl').value.trim();
      const products=[...structureDialog.querySelectorAll('[name="manualProducts"]:checked')].map(input=>input.value);
      const normalize=value=>value.replace(/[^\p{L}\p{N}]/gu,'').toLowerCase();
      if(!name||Object.values(D.profiles).some(p=>p.country===country&&normalize(p.name)===normalize(name)))throw new Error('같은 국가에 같은 이름의 쇼핑몰이 있습니다.');
      if(url&&!/^https?:\/\//i.test(url))throw new Error('홈페이지 주소는 http 또는 https로 입력하세요.');
      if(!products.length)throw new Error('제품군을 하나 이상 선택하세요.');
      structureUndo();
      const key=prefix+'/manual_'+crypto.randomUUID().replaceAll('-','');
      D.profiles[key]={country,name,region:'',currency:'',queries:Object.fromEntries(products.map(c=>[c,''])),bsr:Object.fromEntries(products.map(c=>[c,url])),mainBase:url,homepage:url,searchUI:true,mainSort:'',bsrSort:'',summary:'',warning:''};
      for(const c of ['all',...products])D.datasets.push({key:key+'/'+c,retailer:key,category:c,title:c==='all'?'공통 컬럼':shortCat[c],fields:[]});
      S.r=key;S.c=products[0];S.scope='common';S.field='';S.q='';$('fieldSearch').value='';S.photo=0;
    });
};
addColumn.onclick=()=>{
  const options=['common',...manualDatasets().map(d=>d.category)];
  manualOpenStructure('컬럼 추가','<label>적용 범위<select id="manualColumnScope">'+options.map(scope=>'<option value="'+scope+'" '+(S.scope===scope?'selected':'')+'>'+ (scope==='common'?'공통':manualCategoryLabel(scope))+'</option>').join('')+'</select></label><label>실제 컬럼명<input id="manualColumnName" required pattern="[A-Za-z_][A-Za-z0-9_]*" maxlength="120" placeholder="예: ref_capacity"></label><label>표시 이름<input id="manualColumnLabel" required maxlength="150" placeholder="예: 냉장고 용량"></label><label class="manual-check"><input id="manualColumnDirect" type="checkbox" checked>쇼핑몰 화면에서 확인하는 값</label><p>추가 후 문구 수정과 이미지 추가·수정에서 설명과 여러 캡처를 등록하세요.</p>',()=>{
    const scope=$('manualColumnScope').value,name=$('manualColumnName').value.trim(),label=$('manualColumnLabel').value.trim();
    if(!/^[A-Za-z_][A-Za-z0-9_]{0,119}$/.test(name)||!label)throw new Error('실제 컬럼명과 표시 이름을 확인하세요.');
    if(manualExcludedFields.has(name))throw new Error('이 컬럼은 매뉴얼 표시에서 제외된 항목입니다.');
    const target=manualAllDatasets().find(d=>d.category===(scope==='common'?'all':scope));
    const shared=manualAllDatasets().find(d=>d.category==='all');
    if(target.fields.some(f=>f.field===name)||shared?.fields.some(f=>f.field===name)||(scope==='common'&&manualDatasets().some(d=>d.fields.some(f=>f.field===name))))throw new Error('이미 등록된 컬럼입니다. 기존 컬럼을 수정하세요.');
    structureUndo();
    target.fields.push({n:Math.max(0,...target.fields.map(f=>f.n))+1,field:name,label,scope:'main · bsr',page:'',position:'',original:'',example:'',note:'',direct:$('manualColumnDirect').checked,images:[]});
    S.scope=scope;if(scope!=='common')S.c=scope;S.field=name;S.photo=0;S.q='';$('fieldSearch').value='';
  });
};
const originalUndo=$('undoEdit').onclick;
$('undoEdit').onclick=()=>{
  const item=undoStack.at(-1);
  if(item?.kind!=='structure'){originalUndo();return;}
  restoreObject(D,item.before);Object.assign(S,item.state);undoStack.length=0;changed();render();showToast('구성 추가를 취소했습니다.');
};
const expandedEditorStatus=renderEditorStatus;
renderEditorStatus=function(){expandedEditorStatus();addRetailer.hidden=addColumn.hidden=!editing;addRetailer.disabled=addColumn.disabled=saveBusy;};

// New images and canonical common text use the selected field, without product switching.
const beforeTextEdit=$('editText').onclick;
$('editText').onclick=()=>{beforeTextEdit();if(S.scope==='common')$('editExample').value=field().example||'';};
const beforeApplyText=$('applyText').onclick;
$('applyText').onclick=()=>{
  if(S.scope!=='common'){beforeApplyText();return;}
  if(!$('textEditForm').reportValidity())return;
  const f=field();pushUndo({kind:'field',target:f,before:cloneValue(f)});
  for(const [id,key] of [['editLabel','label'],['editScope','scope'],['editPage','page'],['editPosition','position'],['editOriginal','original'],['editExample','example'],['editNote','note']])f[key]=$(id).value.trim();
  f.userEdited=true;f.commonEdited=true;changed();renderFields();renderLesson();$('textEditor').close();showToast('공통 내용을 적용했습니다. 저장을 눌러 보관하세요.');
};
