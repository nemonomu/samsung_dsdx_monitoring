
(function(){
'use strict';
const D=JSON.parse(document.getElementById('guide-data').textContent),$=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths={grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',external:'<path d="M14 4h6v6M20 4l-9 9M10 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/>',left:'<path d="m14 6-6 6 6 6"/>',right:'<path d="m10 6 6 6-6 6"/>',zoom:'<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',tv:'<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>',ref:'<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M6 9h12M9 5v2m0 5v4"/>',wash:'<rect x="4" y="2" width="16" height="20" rx="2"/><circle cx="12" cy="14" r="5"/><path d="M7 6h2m3 0h1"/>',info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',lock:'<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/>',image:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 6-6 4 4 3-3 5 5"/>'};
const icon=n=>'<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+paths[n]+'</svg>';
const countries=[['미국','US'],['독일','DE'],['스페인','ES'],['멕시코','MX'],['태국','TH']],shortCat={tv:'TV',ref:'냉장고',ldy:'세탁기',ldy_dryer:'건조기',dryer:'건조기'};
let S={country:'미국',r:'SEA/costco',c:'ref',mode:'main',field:'ref_capacity',q:'',scene:'전체',photo:0,view:'full'};
const ds=()=>D.datasets.find(x=>x.retailer===S.r&&x.category===S.c),profile=()=>D.profiles[S.r],field=()=>ds().fields.find(f=>f.field===S.field)||ds().fields[0];
const entry=()=>{const p=profile(),q=encodeURIComponent(p.queries[S.c]);return S.mode==='main'||p.bsrSearch?(p.searchUI?p.mainBase:p.mainBase+q):p.bsr[S.c]};
function photos(){return D.photos.filter(p=>p.retailer===S.r&&(p.category===S.c||p.category==='all')&&p.boxes.some(b=>b.fields.includes(S.field))).sort((a,b)=>Number(!!a.commonExample)-Number(!!b.commonExample)||score(b)-score(a))}
function score(p){return (p.preferredOverview?100:0)+(/capacity|screen_size/.test(S.field)&&/사양/.test(p.stage)?3:0)+(p.stage.startsWith('상세')?1:0)}
function shownPhotos(){return photos()}
function currentPhoto(){const a=shownPhotos();S.photo=Math.min(S.photo,Math.max(0,a.length-1));return a[S.photo]}
function defaultField(){const f=ds().fields.find(f=>['ref_capacity','ldy_capacity','capacity','screen_size'].includes(f.field));S.field=f?.field||ds().fields.find(f=>f.direct)?.field||ds().fields[0].field}
function selectDataset(){S.q='';$('fieldSearch').value='';S.scene='전체';S.photo=0;defaultField();render()}
function setField(f){S.field=f;S.scene='전체';S.photo=0;renderFields();renderLesson();$('announcement').textContent=field().label+' 화면 안내';}
function group(f){if(!f.direct)return '수집 관리 · 기타';if(/capacity|screen_size|loading_type|refrigerator_type/.test(f.field))return '크기 · 용량 · 유형';if(/price|savings/.test(f.field))return '가격';if(/review|rating/.test(f.field))return '리뷰';return '상품 정보'}
function navigation(){
$('countryNav').innerHTML=countries.map(([n,c])=>'<button class="country '+(S.country===n?'on':'')+'" data-country="'+n+'" aria-pressed="'+(S.country===n)+'"><span class="countrycode">'+c+'</span>'+n+'<span class="count">'+Object.values(D.profiles).filter(p=>p.country===n).length+'</span></button>').join('');
$('retailerNav').innerHTML=Object.entries(D.profiles).filter(([r,p])=>p.country===S.country).map(([r,p])=>'<button class="retailer '+(r===S.r?'on':'')+'" data-retailer="'+r+'" aria-pressed="'+(r===S.r)+'">'+esc(p.name)+'</button>').join('');
$('categoryNav').innerHTML=D.datasets.filter(d=>d.retailer===S.r).map(d=>'<button class="category '+(d.category===S.c?'on':'')+'" data-category="'+d.category+'" aria-pressed="'+(d.category===S.c)+'">'+icon(d.category==='tv'?'tv':d.category==='ref'?'ref':'wash')+shortCat[d.category]+'</button>').join('');
$('countryNav').querySelectorAll('button').forEach(b=>b.onclick=()=>{S.country=b.dataset.country;S.r=Object.keys(D.profiles).find(r=>D.profiles[r].country===S.country);if(!D.datasets.some(d=>d.retailer===S.r&&d.category===S.c))S.c='ref';selectDataset()});
$('retailerNav').querySelectorAll('button').forEach(b=>b.onclick=()=>{S.r=b.dataset.retailer;if(!D.datasets.some(d=>d.retailer===S.r&&d.category===S.c))S.c='ref';selectDataset()});
$('categoryNav').querySelectorAll('button').forEach(b=>b.onclick=()=>{S.c=b.dataset.category;selectDataset()});
}
function render(){navigation();const p=profile();$('breadcrumb').textContent='dx 메뉴얼 / '+S.country+' / '+p.name;$('heading').innerHTML=esc(p.name)+'<span>/</span>'+shortCat[S.c];$('mainMode').classList.toggle('on',S.mode==='main');$('bsrMode').classList.toggle('on',S.mode==='bsr');$('mainMode').setAttribute('aria-pressed',S.mode==='main');$('bsrMode').setAttribute('aria-pressed',S.mode==='bsr');$('entryLink').href=entry();$('routeSummary').innerHTML=p.blocked?'<span class="blocked">현재 페이지 접근 제한 · 확인 방법 안내</span>':'<strong>'+esc(S.mode==='main'?'검색 목록에서 시작':'카테고리·정렬 기준에서 시작')+'</strong> · '+esc(p.queries[S.c]);$('fieldCount').textContent=ds().fields.length+'개';$('footerStatus').textContent='확인일 '+D.date+' · '+S.r;renderFields();renderLesson();}
function renderFields(){const q=S.q.toLowerCase(),rows=manualScopedFields().filter(f=>!q||[f.field,f.label,f.position,f.original].join(' ').toLowerCase().includes(q));const groups=['상품 정보','크기 · 용량 · 유형','가격','리뷰','수집 관리 · 기타'];$('fieldList').innerHTML=groups.map(g=>{const fs=rows.filter(f=>group(f)===g);return fs.length?'<section class="fieldgroup"><h3 class="fieldgroup-title">'+g+'<span>'+fs.length+'</span></h3>'+fs.map(f=>'<button class="fieldbtn '+(f.field===S.field?'on':'')+'" data-field="'+f.field+'" aria-pressed="'+(f.field===S.field)+'"><span class="fieldnum">'+f.n+'</span><span><strong>'+esc(f.label)+'</strong><code>'+esc(f.field)+'</code></span>'+(f.images?.length?'<span class="photo-dot" title="번호 캡처 있음"></span>':'')+'</button>').join('')+'</section>':''}).join('')||'<div class="notfound">찾는 컬럼이 없어요.<br>다른 이름으로 검색해 보세요.</div>';$('fieldList').querySelectorAll('[data-field]').forEach(b=>b.onclick=()=>setField(b.dataset.field))}
function svg(p,full=false){
const all=p.boxes.map(b=>({...b,ns:b.fields.map(f=>ds().fields.find(r=>r.field===f)?.n).filter(Boolean)})).filter(b=>b.ns.length),sel=all.filter(b=>b.fields.includes(S.field));let vb=[0,0,p.width,p.height];

if(full){
 const fs=Math.max(16,p.width/85),stroke=Math.max(3,p.width/500);
 const marks=sel.map(b=>{const nums=b.ns.join(' · '),bw=Math.min(p.width,Math.max(fs*1.7,nums.length*fs*.62+fs)),bh=fs*1.6,x=Math.max(0,Math.min(p.width-bw,b.x-4)),y=b.y>bh+6?b.y-bh-6:Math.min(p.height-bh,b.y+b.h+6);
 return '<rect x="'+b.x+'" y="'+b.y+'" width="'+b.w+'" height="'+b.h+'" rx="3" fill="#dc4352" fill-opacity=".04" stroke="#dc4352" stroke-width="'+stroke+'"/><rect x="'+x+'" y="'+y+'" width="'+bw+'" height="'+bh+'" rx="5" fill="#dc4352"/><text x="'+(x+bw/2)+'" y="'+(y+bh*.71)+'" text-anchor="middle" fill="white" font-family="Arial,sans-serif" font-size="'+fs+'" font-weight="700">'+nums+'</text>'
 }).join('');
 return '<svg viewBox="0 0 '+p.width+' '+p.height+'" preserveAspectRatio="xMidYMid meet" role="img" aria-label="'+esc(field().label)+' 전체 화면 · '+field().n+'번 위치"><rect width="'+p.width+'" height="'+p.height+'" fill="white"/><image href="'+esc(photoSrc(p))+'" width="'+p.width+'" height="'+p.height+'"/>'+marks+'</svg>';
}
if(!full&&sel.length){const x0=Math.min(...sel.map(b=>b.x)),y0=Math.min(...sel.map(b=>b.y)),x1=Math.max(...sel.map(b=>b.x+b.w)),y1=Math.max(...sel.map(b=>b.y+b.h));const w=Math.min(p.width,Math.max(x1-x0+180,620)),h=Math.min(p.height,Math.max(y1-y0+110,180)),x=Math.max(0,Math.min(p.width-w,x0-90)),y=Math.max(0,Math.min(p.height-h,y0-55));vb=[x,y,w,h]}
let lx=vb[0]+12;const labels=sel.map(b=>{const nums=b.ns.join(' · '),w=Math.max(32,nums.length*9+18),x=lx;lx+=w+12;return '<path d="M'+(x+w/2)+' '+(vb[1]-8)+' L'+(b.x+12)+' '+(b.y-4)+'" stroke="#dc4352" stroke-width="1.5" fill="none"/><rect x="'+x+'" y="'+(vb[1]-34)+'" width="'+w+'" height="26" rx="6" fill="#dc4352"/><text x="'+(x+w/2)+'" y="'+(vb[1]-16)+'" text-anchor="middle" fill="white" font-family="Arial,sans-serif" font-size="14" font-weight="700">'+nums+'</text>'}).join('');
const clipId='crop-'+p.name+'-'+field().n;return '<svg viewBox="'+[vb[0],vb[1]-44,vb[2],vb[3]+44].join(' ')+'" role="img" aria-label="'+esc(field().label)+' '+field().n+'번 위치"><defs><clipPath id="'+clipId+'"><rect x="'+vb[0]+'" y="'+(vb[1]-44)+'" width="'+vb[2]+'" height="'+(vb[3]+44)+'"/></clipPath></defs><g clip-path="url(#'+clipId+')"><rect x="'+vb[0]+'" y="'+(vb[1]-44)+'" width="'+vb[2]+'" height="'+(vb[3]+44)+'" fill="white"/><image href="'+esc(photoSrc(p))+'" width="'+p.width+'" height="'+p.height+'"/><rect x="'+vb[0]+'" y="'+(vb[1]-44)+'" width="'+vb[2]+'" height="44" fill="white"/>'+labels+sel.map(b=>'<rect x="'+(b.x-4)+'" y="'+(b.y-4)+'" width="'+(b.w+8)+'" height="'+(b.h+8)+'" rx="3" fill="none" stroke="#dc4352" stroke-width="2.8"/>').join('')+'</g></svg>';
}
function renderLesson(){const f=field(),p=profile(),all=photos(),a=shownPhotos(),photo=currentPhoto();$('lessonNumber').textContent=f.n;$('lessonTitle').textContent=f.label;$('lessonCode').textContent=f.field;const ix=ds().fields.indexOf(f);$('prevField').disabled=ix===0;$('nextField').disabled=ix===ds().fields.length-1;

if(renderFieldWithoutImage(f,p,photo))return;
$('sceneTabs').setAttribute('aria-label','이미지 보기 방식');
$('sceneTabs').innerHTML=photo?[['full','전체 화면'],['data','수집데이터']].map(([v,label])=>'<button class="scene-tab '+(S.view===v?'on':'')+'" data-view="'+v+'" aria-pressed="'+(S.view===v)+'">'+label+'</button>').join(''):'<span class="scene-tab on">'+(f.direct?'확인 위치 안내':'화면에 직접 표시되지 않는 값')+'</span>';
$('sceneTabs').querySelectorAll('button').forEach(b=>b.onclick=()=>{S.view=b.dataset.view;renderLesson()});
$('canvas').dataset.view=S.view;
$('zoomOpen').hidden=!photo;$('originalLink').hidden=!photo;$('commonNote').hidden=!photo?.commonExample;if(photo?.commonExample)$('commonNote').textContent='냉장고 표본으로 보는 공통 위치입니다. 선택한 제품군의 실제 값과 구분해 주세요.';
if(photo){$('canvas').innerHTML='<div class="view-caption">'+(S.view==='full'?'이미지 전체에서 <strong>'+f.n+'번 박스</strong>의 위치를 확인하세요.':'같은 캡처의 <strong>'+f.n+'번 박스 주변</strong>을 확대했습니다.')+'</div>'+svg(photo,S.view==='full');$('originalLink').href=photoSrc(photo);$('photoSource').innerHTML=esc(photo.stage)+(photo.url?' · <a href="'+esc(photo.url)+'" target="_blank" rel="noopener">출처 페이지 ↗</a>':' · 제공된 캡처')+'<br>'+esc(photo.region)+' · '+esc(photo.date);$('photoPager').innerHTML='<button id="prevPhoto" aria-label="이전 캡처" '+(S.photo===0?'disabled':'')+'>‹</button><select id="captureSelect" aria-label="캡처 선택">'+a.map((item,i)=>'<option value="'+i+'" '+(i===S.photo?'selected':'')+'>'+(i+1)+' / '+a.length+' · '+esc(item.stage)+'</option>').join('')+'</select><button id="nextPhoto" aria-label="다음 캡처" '+(S.photo===a.length-1?'disabled':'')+'>›</button>';$('captureSelect').onchange=e=>{S.photo=Number(e.target.value);renderLesson()};$('prevPhoto').onclick=()=>{S.photo--;renderLesson()};$('nextPhoto').onclick=()=>{S.photo++;renderLesson()};}
else{$('canvas').innerHTML='<div class="empty"><div class="emptyicon">'+icon(p.blocked?'lock':f.direct?'image':'info')+'</div><strong>'+esc(p.blocked?'현재 사이트 화면을 확인하지 못했어요.':f.direct?'이번 표본에는 번호 캡처가 없어요.':'쇼핑몰에 직접 표시되는 값이 아니에요.')+'</strong><p>'+esc(p.blocked?p.blocked:f.direct?'아래의 확인 위치와 원문 항목명을 따라 찾아보세요. 확인하지 않은 화면을 예시로 만들지 않았습니다.':'상품 화면의 숫자를 찾는 대신, 아래에서 이 컬럼의 의미와 출처를 확인하세요.')+'</p></div>';$('photoSource').textContent=p.region;$('photoPager').textContent=p.blocked?'현재 화면 미확인':'위치 · 의미 안내';}
const shownExample=photo?.sampleValues?.[f.field]??f.example;
$('inspector').innerHTML='<div class="facts"><div class="fact"><div class="facttitle">'+(photo?.commonExample?'선택 제품의 값 · 확인 상태':'확인하는 값')+'</div><div class="example '+(shownExample.length>24?'long':'')+'">'+(f.field==='product_url'&&shownExample.startsWith('http')?'<a target="_blank" rel="noopener" href="'+esc(shownExample)+'">표본 상품 열기 ↗</a>':esc(shownExample))+'</div></div><div class="fact"><div class="facttitle">어디서 찾나요?</div><span class="sourcepill">'+esc(f.page)+'</span><div class="where">'+esc(f.position)+'</div></div><div class="fact"><div class="facttitle">화면의 원문 항목</div><div class="origin">'+esc(f.original)+'</div><div class="facttitle" style="margin-top:12px">수집 구분 · '+esc(f.scope)+'</div></div></div><details class="attention" '+(/capacity|screen_size/.test(f.field)?'open':'')+'><summary>'+icon('info')+'헷갈리기 쉬운 부분</summary><p>'+esc(f.note)+'</p>'+(photo?'<p>'+esc(photo.note)+'</p>':'')+'</details>';
}
function openInfo(title,content){$('infoTitle').textContent=title;$('infoBody').innerHTML=content;$('infoDialog').showModal()}
function routeInfo(){const p=profile();openInfo(profile().name+' 방문 방법','<h3>'+S.mode+' · '+shortCat[S.c]+'</h3><p><a href="'+esc(entry())+'" target="_blank" rel="noopener">쇼핑몰에서 시작하기 ↗</a></p><p>검색어 <strong>'+esc(p.queries[S.c])+'</strong><br>정렬 · '+esc(S.mode==='main'?p.mainSort:p.bsrSort)+'</p><h3>목록과 상세에서 확인할 것</h3><p>'+esc(p.summary)+'</p><h3>사용한 지역</h3><p>'+esc(p.region)+'</p><h3>확인할 때 주의하세요</h3><p>'+esc(p.warning)+'</p>'+(p.blocked?'<p>'+esc(p.blocked)+'</p>':''))}
function renderTable(){const q=$('tableSearch').value.toLowerCase();$('tableTitle').textContent=profile().name+' · '+shortCat[S.c]+' 전체 '+ds().fields.length+'개 컬럼';$('tableRows').innerHTML=ds().fields.filter(f=>!q||[f.field,f.label,f.position,f.original].join(' ').toLowerCase().includes(q)).map(f=>'<tr><td><button class="tablelink" data-jump="'+f.field+'">'+f.n+' →</button></td><td><code>'+esc(f.field)+'</code><br><strong>'+esc(f.label)+'</strong></td><td>'+esc(f.scope)+'</td><td><strong>'+esc(f.page)+'</strong><br>'+esc(f.position)+'<small>'+esc(f.original)+'</small></td><td>'+esc(f.example)+'<small>'+esc(f.note)+'</small></td></tr>').join('');$('tableRows').querySelectorAll('[data-jump]').forEach(b=>b.onclick=()=>{$('tableDialog').close();setField(b.dataset.jump)})}
function coverage(){openInfo('참고 자료와 확인 범위','<p>실제 수집 컬럼 515개 · 24개 제품군 조합. 표와 화면의 번호는 각 데이터셋 안에서 유지됩니다. 사진과 값은 '+D.date+' 확인 표본이며 조회 시점·지역·옵션에 따라 바뀔 수 있습니다.</p><div class="covergrid">'+Object.entries(D.profiles).map(([r,p])=>'<article><strong>'+esc(p.country+' · '+p.name)+'</strong>'+D.datasets.filter(d=>d.retailer===r).map(d=>shortCat[d.category]).join(' · ')+'<p>'+esc(p.blocked||'목록·상세 표본 확인. 일부 가격·리뷰는 냉장고 공통 위치 예시로 구분했습니다.')+'</p></article>').join('')+'</div><h3>별도로 확인해야 하는 차이</h3><p>Expert 냉장고 TSK5O881ES의 제목 124 l와 사양 142가 다릅니다. 현재 수집은 제목 우선입니다. Kühlschränke 검색은 일반 목록 대신 안내 페이지로 이동했습니다. Liverpool 세탁 용량 보완 후보에 Capacidad de secado도 포함되어 있어 세탁·건조 라벨을 구분해야 합니다.</p><h3>확인하지 못한 항목</h3><p>접근이 제한된 사이트의 현재 가격·사양·리뷰, Costco 로그인 전 숨겨진 회원 가격은 확인하지 못했습니다. 제품별 캡처가 없는 컬럼은 위치 안내 또는 명시된 공통 예시로 구분했습니다. Expert의 같은 모델 PDF 보완 경로는 안내만 포함하며 PDF 내용 자체는 검증하지 않았습니다.</p><details class="reference"><summary>참고 엑셀의 원래 번호 보기 · 92개 행</summary><p>미국 참고 엑셀의 데이터셋은 컬럼 정의 표입니다. BestBuy 냉장고 1–21, Lowe’s 냉장고 31–55, BestBuy 세탁기 61–81, Lowe’s 세탁기 91–115를 보존했습니다. 현재 프로젝트의 다른 리테일러에 이 컬럼을 그대로 적용하지 않았으며 각 실제 스키마 순서로 번호를 부여했습니다.</p><div class="tablewrap"><table><thead><tr><th>번호</th><th>대상</th><th>화면 구분</th><th>컬럼</th><th>설명</th></tr></thead><tbody>'+D.reference.map(r=>'<tr><td>'+esc(r.B)+'</td><td>'+esc(r.C+' / '+r.F+' / '+r.D)+'</td><td>'+esc(r.G)+'</td><td><code>'+esc(r.H)+'</code></td><td>'+esc(r.I)+'</td></tr>').join('')+'</tbody></table></div></details><p>허용된 코드·참고 엑셀은 읽기 전용으로 사용했습니다. 프로젝트 및 DB를 변경하지 않았습니다. 변경 내용은 저장 버튼을 눌러 서버에 보관합니다.</p>')}
function help(){openInfo('세 단계면 충분해요.','<div class="helpsteps"><article><b>01</b><h3>어디를 볼지 고르세요.</h3><p>국가 → 리테일러를 선택하고, 공통 컬럼 또는 제품군별 탭을 선택합니다. 공통 컬럼의 화면 예시는 제품군별로 바꿀 수 있습니다. main과 bsr의 방문 링크·정렬은 상단에서 바꿀 수 있어요.</p></article><article><b>02</b><h3>궁금한 컬럼을 누르세요.</h3><p>한국어 이름이나 실제 컬럼명으로 찾을 수 있어요. 용량·가격·리뷰처럼 묶인 목록에서 하나씩 살펴보세요.</p></article><article><b>03</b><h3>전체 위치와 수집할 값을 확인하세요.</h3><p>전체 화면에서 빨간 번호 박스로 위치를 확인하고, 수집데이터에서 박스 주변을 확대해 값을 읽으세요. 캡처 선택에서 목록·상세 사진을 바꿀 수 있습니다.</p></article></div><p>전체 컬럼 표와 관리값도 그대로 보존되어 있습니다. 현재 확인하지 못한 항목은 그 상태를 함께 안내합니다.</p>')}
$('brandIcon').innerHTML=icon('grid');$('searchIcon').innerHTML=icon('search');$('externalIcon').innerHTML=icon('external');$('prevField').innerHTML=icon('left');$('nextField').innerHTML=icon('right');$('zoomOpen').innerHTML=icon('zoom')+'크게 보기';
$('fieldSearch').oninput=e=>{S.q=e.target.value;renderFields()};$('mainMode').onclick=()=>{S.mode='main';render()};$('bsrMode').onclick=()=>{S.mode='bsr';render()};$('prevField').onclick=()=>setField(ds().fields[ds().fields.indexOf(field())-1].field);$('nextField').onclick=()=>setField(ds().fields[ds().fields.indexOf(field())+1].field);$('routeDetails').onclick=routeInfo;$('coverageOpen').onclick=coverage;document.querySelectorAll('[data-help]').forEach(b=>b.onclick=help);document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>b.closest('dialog').close());$('tableOpen').onclick=()=>{$('tableSearch').value='';renderTable();$('tableDialog').showModal()};$('tableSearch').oninput=renderTable;$('zoomOpen').onclick=()=>{const p=currentPhoto();if(!p)return;$('zoomTitle').textContent=field().n+' · '+field().label;$('zoomBody').innerHTML=svg(p,S.view==='full')+'<p class="zoomcaption">'+esc(p.note)+'</p>';$('zoomDialog').showModal()};
/* Local editor. No upload or network service is used for user images. */
function photoSrc(p){return p.customImage||(D.assets&&D.assets[p.name])||('images/'+p.name+'.jpg')}
let editing=false,revision=0,downloadedRevision=0,undoStack=[],workingPhoto=null,editingPhotoIndex=-1,selectedBox=-1,drawing=false,drawStart=null,newUpload=false,toastTimer=null,exportBlob=null,exportRevision=0,saveHandle=null,saveBusy=false,lastSaveTime='';
function cloneValue(v){return JSON.parse(JSON.stringify(v))}
function showToast(message){$('editorToast').textContent=message;$('editorToast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{$('editorToast').hidden=true},3500)}

function changed(){revision++;renderEditorStatus()}
function refreshImageLinks(){for(const d of D.datasets)for(const f of d.fields){f.images=[...new Set(D.photos.filter(p=>p.retailer===d.retailer&&(p.category===d.category||p.category==='all')&&p.boxes.some(b=>b.fields.includes(f.field))).map(p=>p.name))];if('verified'in f)f.verified=Boolean(f.images.length)}}
function restoreObject(target,before){for(const key of Object.keys(target))delete target[key];Object.assign(target,cloneValue(before))}
function pushUndo(item){undoStack.push(item);if(undoStack.length>25)undoStack.shift()}
function today(){const t=new Date();return [t.getFullYear(),String(t.getMonth()+1).padStart(2,'0'),String(t.getDate()).padStart(2,'0')].join('-')}
const originalRenderLesson=renderLesson;
renderLesson=function(){originalRenderLesson();if(currentPhoto()){const p=currentPhoto(),mime=photoSrc(p).slice(0,40);$('originalLink').download=p.name+(mime.includes('image/jpeg')?'.jpg':mime.includes('image/webp')?'.webp':'.png');}renderEditorStatus()};
$('editModeToggle').onclick=()=>{editing=!editing;renderEditorStatus();if(editing)showToast('문구와 이미지를 적용한 뒤 저장 또는 Ctrl+S를 눌러 주세요.');else if(revision!==downloadedRevision)showToast('보기 모드로 전환했습니다. 변경 내용을 보관하려면 저장 또는 Ctrl+S를 눌러 주세요.')};
$('editText').onclick=()=>{const f=field();$('editIdentity').innerHTML='<strong>'+f.n+'번</strong> · <code>'+esc(f.field)+'</code> · '+esc(profile().name)+' / '+shortCat[S.c];for(const [id,key] of [['editLabel','label'],['editScope','scope'],['editPage','page'],['editPosition','position'],['editOriginal','original'],['editExample','example'],['editNote','note']])$(id).value=(key==='example'?(currentPhoto()?.sampleValues?.[f.field]??f[key]):f[key])||'';$('textEditor').showModal()};
$('applyText').onclick=()=>{if(!$('textEditForm').reportValidity())return;const f=field();const samplePhoto=currentPhoto()?.sampleValues?.[f.field]!==undefined?currentPhoto():null;pushUndo({kind:'field',target:f,before:cloneValue(f),samplePhoto,beforeSamples:samplePhoto?cloneValue(samplePhoto.sampleValues):null});for(const [id,key] of [['editLabel','label'],['editScope','scope'],['editPage','page'],['editPosition','position'],['editOriginal','original'],['editExample','example'],['editNote','note']])f[key]=$(id).value.trim();if(samplePhoto)samplePhoto.sampleValues[f.field]=f.example;f.userEdited=true;changed();renderFields();renderLesson();$('textEditor').close();showToast('컬럼 내용이 적용되었습니다. Ctrl+S로 서버에 저장하세요.')};
$('undoEdit').onclick=()=>{const item=undoStack.pop();if(!item)return;if(item.kind==='addPhoto'){const i=D.photos.indexOf(item.target);if(i>=0)D.photos.splice(i,1)}else restoreObject(item.target,item.before);if(item.samplePhoto)item.samplePhoto.sampleValues=cloneValue(item.beforeSamples);refreshImageLinks();changed();renderFields();renderLesson();showToast('최근 변경을 취소했습니다.')};
function availableEditorPhotos(){return D.photos.map((p,i)=>({p,i})).filter(({p})=>p.retailer===S.r&&(p.category===S.c||p.category==='all'))}
function loadPhotoDraft(index){editingPhotoIndex=index;workingPhoto=index>=0?cloneValue(D.photos[index]):null;selectedBox=workingPhoto?.boxes.findIndex(b=>b.fields.includes(S.field))??-1;if(selectedBox<0&&workingPhoto?.boxes.length)selectedBox=0;drawing=false;drawStart=null;$('imageError').textContent='';renderPhotoEditor()}
function photoMetadataToDraft(){if(!workingPhoto)return;for(const [id,key] of [['editPhotoStage','stage'],['editPhotoNote','note'],['editPhotoUrl','url'],['editPhotoDate','date'],['editPhotoRegion','region'],['editPhotoCommon','commonExample']])workingPhoto[key]=$(id).value.trim()}
function renderPhotoEditor(){const choices=availableEditorPhotos();$('editPhotoSelect').innerHTML=(editingPhotoIndex<0?'<option value="-1">새 이미지</option>':'')+choices.map(({p,i})=>'<option value="'+i+'" '+(i===editingPhotoIndex?'selected':'')+'>'+esc(p.stage)+(p.commonExample?' · 공통 예시':'')+' / '+esc(p.name)+'</option>').join('');if(!choices.length&&editingPhotoIndex>=0)$('editPhotoSelect').innerHTML='<option value="-1">이미지를 추가하세요.</option>';for(const [id,key] of [['editPhotoStage','stage'],['editPhotoNote','note'],['editPhotoUrl','url'],['editPhotoDate','date'],['editPhotoRegion','region'],['editPhotoCommon','commonExample']])$(id).value=workingPhoto?.[key]||'';renderImageStage();renderBoxControls()}
function renderImageStage(){const p=workingPhoto;$('drawBox').classList.toggle('on',drawing);$('drawBox').textContent=drawing?'그리기 중 · 드래그하세요':'＋ 번호 박스 그리기';$('imageStage').classList.toggle('drawing',drawing);$('drawBox').disabled=!p;$('replacePhoto').disabled=!p;if(!p){$('imageStage').innerHTML='<div class="empty"><div class="emptyicon">'+icon('image')+'</div><strong>직접 준비한 캡처를 넣어 보세요.</strong><p>‘새 이미지 추가’를 누르면 컴퓨터의 사진을 선택할 수 있습니다.</p></div>';return}const fs=Math.max(13,p.width/80);$('imageStage').innerHTML='<svg id="annotationCanvas" viewBox="0 0 '+p.width+' '+p.height+'" aria-label="번호 박스 편집용 이미지"><image href="'+esc(photoSrc(p))+'" width="'+p.width+'" height="'+p.height+'"/>'+p.boxes.map((b,i)=>{const nums=b.fields.map(f=>ds().fields.find(v=>v.field===f)?.n).filter(Boolean).join(' · '),col=i===selectedBox?'#375de7':'#dc4352';return '<g data-box-index="'+i+'"><rect x="'+b.x+'" y="'+b.y+'" width="'+b.w+'" height="'+b.h+'" fill="'+col+'" fill-opacity=".06" stroke="'+col+'" stroke-width="'+Math.max(2,p.width/600)+'"/><rect x="'+b.x+'" y="'+Math.max(0,b.y-fs*1.6)+'" width="'+Math.max(fs*2,nums.length*fs*.7+fs)+'" height="'+fs*1.5+'" rx="3" fill="'+col+'"/><text x="'+(b.x+fs*.5)+'" y="'+Math.max(fs*1.1,b.y-fs*.45)+'" fill="white" font-size="'+fs+'" font-family="Arial" font-weight="700">'+esc(nums||'?')+'</text></g>'}).join('')+'<rect id="draftBox" fill="#375de7" fill-opacity=".1" stroke="#375de7" stroke-width="'+Math.max(2,p.width/600)+'" stroke-dasharray="7 4" visibility="hidden"/></svg>'}
function renderBoxControls(){const p=workingPhoto,b=p?.boxes[selectedBox];$('boxList').innerHTML=p?.boxes.length?p.boxes.map((v,i)=>'<button data-select-box="'+i+'" class="'+(i===selectedBox?'on':'')+'">박스 '+(i+1)+' · '+v.fields.map(f=>ds().fields.find(r=>r.field===f)?.n).filter(Boolean).join(', ')+'</button>').join(''):'<span class="editstatus">아직 번호 박스가 없어요.</span>';$('boxList').querySelectorAll('button').forEach(button=>button.onclick=()=>{photoMetadataToDraft();selectedBox=Number(button.dataset.selectBox);renderImageStage();renderBoxControls()});for(const [id,k]of[['boxX','x'],['boxY','y'],['boxW','w'],['boxH','h']]){$(id).disabled=!b;$(id).value=b?Math.round(b[k]):''}$('removeBox').disabled=!b;const selected=b?b.fields:[S.field];$('boxFields').innerHTML=ds().fields.map(f=>'<label><input type="checkbox" value="'+esc(f.field)+'" '+(selected.includes(f.field)?'checked':'')+'><span>'+f.n+' · '+esc(f.label)+'</span></label>').join('');$('boxFields').querySelectorAll('input').forEach(input=>input.onchange=()=>{if(!workingPhoto?.boxes[selectedBox])return;workingPhoto.boxes[selectedBox].fields=selectedBoxFields();renderImageStage();$('imageError').textContent=''})}
function selectedBoxFields(){return Array.from($('boxFields').querySelectorAll('input:checked')).map(x=>x.value)}
function pointerPoint(e){const svg=$('annotationCanvas');if(!svg)return null;const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;return pt.matrixTransform(svg.getScreenCTM().inverse())}
$('imageStage').onpointerdown=e=>{if(!workingPhoto)return;if(!drawing){const group=e.target.closest('[data-box-index]');if(group){photoMetadataToDraft();selectedBox=Number(group.dataset.boxIndex);renderImageStage();renderBoxControls()}return}const pt=pointerPoint(e);if(!pt||pt.x<0||pt.y<0||pt.x>workingPhoto.width||pt.y>workingPhoto.height)return;e.preventDefault();drawStart={x:pt.x,y:pt.y};$('imageStage').setPointerCapture(e.pointerId)};
$('imageStage').onpointermove=e=>{if(!drawStart)return;const pt=pointerPoint(e);if(!pt)return;const x=Math.max(0,Math.min(workingPhoto.width,pt.x)),y=Math.max(0,Math.min(workingPhoto.height,pt.y)),r=$('draftBox');r.setAttribute('visibility','visible');r.setAttribute('x',Math.min(x,drawStart.x));r.setAttribute('y',Math.min(y,drawStart.y));r.setAttribute('width',Math.abs(x-drawStart.x));r.setAttribute('height',Math.abs(y-drawStart.y))};
$('imageStage').onpointerup=e=>{if(!drawStart)return;const pt=pointerPoint(e),start=drawStart;drawStart=null;if(!pt)return;const x=Math.max(0,Math.min(workingPhoto.width,pt.x)),y=Math.max(0,Math.min(workingPhoto.height,pt.y)),box={x:Math.min(x,start.x),y:Math.min(y,start.y),w:Math.abs(x-start.x),h:Math.abs(y-start.y),fields:selectedBoxFields(),text:''};if(box.w>3&&box.h>3){if(!box.fields.length)box.fields=[S.field];photoMetadataToDraft();workingPhoto.boxes.push(box);selectedBox=workingPhoto.boxes.length-1;drawing=false;renderImageStage();renderBoxControls()}else renderImageStage()};
$('imageStage').onpointercancel=()=>{drawStart=null;renderImageStage()};
$('editImage').onclick=()=>{const p=currentPhoto(),items=availableEditorPhotos();loadPhotoDraft(p?D.photos.indexOf(p):(items[0]?.i??-1));$('imageEditor').showModal()};
$('editPhotoSelect').onchange=e=>loadPhotoDraft(Number(e.target.value));
$('drawBox').onclick=()=>{drawing=!drawing;drawStart=null;renderImageStage();if(drawing)showToast('값을 둘러싸도록 드래그하세요. 연결할 컬럼은 오른쪽에서 고릅니다.')};
function boxInputsToDraft(){const p=workingPhoto,b=p?.boxes[selectedBox];if(!b)return;for(const [id,k]of[['boxX','x'],['boxY','y'],['boxW','w'],['boxH','h']]){const raw=$(id).value,v=Number(raw);if(raw!==''&&Number.isFinite(v))b[k]=Math.max(k==='x'||k==='y'?0:1,v)}b.x=Math.min(b.x,p.width-1);b.y=Math.min(b.y,p.height-1);b.w=Math.min(b.w,p.width-b.x);b.h=Math.min(b.h,p.height-b.y)}
for(const id of ['boxX','boxY','boxW','boxH']){$(id).oninput=()=>{boxInputsToDraft();renderImageStage()};$(id).onchange=()=>{boxInputsToDraft();renderImageStage();renderBoxControls()}}

$('removeBox').onclick=()=>{if(!workingPhoto||selectedBox<0)return;workingPhoto.boxes.splice(selectedBox,1);selectedBox=Math.min(selectedBox,workingPhoto.boxes.length-1);renderImageStage();renderBoxControls()};
$('replacePhoto').onclick=()=>{newUpload=false;$('photoFile').value='';$('photoFile').click()};
$('addPhoto').onclick=()=>{newUpload=true;$('photoFile').value='';$('photoFile').click()};
$('photoFile').onchange=async e=>{const file=e.target.files?.[0];if(!file)return;if(!['image/png','image/jpeg','image/webp'].includes(file.type)){$('imageError').textContent='PNG, JPG, WEBP 이미지를 선택하세요.';return}if(file.size>15*1024*1024){$('imageError').textContent='15MB 이하의 이미지를 선택하세요.';return}try{const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file)});const size=await new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve({width:im.naturalWidth,height:im.naturalHeight});im.onerror=reject;im.src=data});photoMetadataToDraft();if(newUpload||!workingPhoto){editingPhotoIndex=-1;workingPhoto={retailer:S.r,category:S.c,stage:'상세',region:profile().region,note:'사용자가 추가한 이미지입니다.',name:'user_photo_'+Date.now(),url:'',date:today(),boxes:[]}}workingPhoto.customImage=data;workingPhoto.width=size.width;workingPhoto.height=size.height;workingPhoto.boxes=[];selectedBox=-1;drawing=false;drawStart=null;$('imageError').textContent='';renderPhotoEditor();showToast('이미지를 불러왔습니다. 번호 박스를 새로 그려 주세요.')}catch{$('imageError').textContent='이미지를 읽지 못했습니다. 다른 파일을 선택하세요.'}};
$('applyImage').onclick=()=>{boxInputsToDraft();photoMetadataToDraft();const p=workingPhoto;if(!p){$('imageError').textContent='이미지를 먼저 추가하세요.';return}if(!p.boxes.length){$('imageError').textContent='값을 가리키는 번호 박스를 한 개 이상 추가하세요.';return}if(p.boxes.some(b=>!b.fields.length)){$('imageError').textContent='모든 박스에 연결할 컬럼을 한 개 이상 선택하세요.';return}if(p.url&&!/^https?:\/\//i.test(p.url)){$('imageError').textContent='출처는 http 또는 https 주소를 입력하거나 비워 두세요.';return}if(!p.stage.trim())p.stage='상세';p.userEdited=true;if(editingPhotoIndex>=0){const target=D.photos[editingPhotoIndex];pushUndo({kind:'photo',target,before:cloneValue(target)});restoreObject(target,p)}else{const target=cloneValue(p);D.photos.push(target);pushUndo({kind:'addPhoto',target})}refreshImageLinks();const appliedPhoto=editingPhotoIndex>=0?D.photos[editingPhotoIndex]:D.photos[D.photos.length-1];const selectedFields=p.boxes[selectedBox]?.fields||[];const linkedFields=p.boxes.flatMap(b=>b.fields);const focusFields=selectedFields.length?selectedFields:linkedFields;S.field=focusFields.includes(S.field)?S.field:(focusFields.find(name=>ds().fields.some(f=>f.field===name))||S.field);S.scene='전체';S.q='';$('fieldSearch').value='';S.photo=Math.max(0,shownPhotos().indexOf(appliedPhoto));changed();renderFields();renderLesson();$('imageEditor').close();showToast('수정한 이미지와 번호가 적용되었습니다. Ctrl+S로 서버에 저장하세요.')};

/* Server persistence is appended below. */
window.addEventListener('beforeunload',e=>{if(revision!==downloadedRevision){e.preventDefault();e.returnValue=''}});


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
    fact(f.direct ? '어디서 찾나요?' : '값의 출처', '<span class="sourcepill">' + esc(f.page) + '</span><div class="where">' + esc(f.position) + '</div>') +
    fact('값 예시', '<div class="example long">' + exampleHtml + '</div>') +
    fact(f.direct ? '화면의 원문 항목' : '관련 항목', esc(f.original)) +
    fact('수집 구분', esc(f.scope)) +
    '</dl>' +
    (f.note ? '<div class="field-info-note"><strong>확인 방법 · 주의사항</strong><p>' + esc(f.note) + '</p></div>' : '');
  return true;
}

// Reviewed shared meanings. Never group an unknown field solely by its name.
const manualCommonDefinitions = {
  retailer_sku_name: '쇼핑몰이 상품에 표시한 이름입니다. 실제 상품명과 표시 위치는 제품군별 예시를 확인하세요.',
  sku: '제조사가 상품을 구분하는 모델명입니다. 쇼핑몰 자체 상품 번호와 구별합니다.',
  final_sku_price: '현재 선택한 상품의 판매가격입니다. 실제 금액과 확인 위치는 제품군별 예시를 확인하세요.',
  original_sku_price: '판매가격과 함께 표시된 비교가격입니다. 화면에 비교가격이 없으면 임의로 만들지 않습니다.',
  savings: '쇼핑몰에 표시된 할인 정보입니다. 금액·비율·문구 등 실제 표시 형태를 확인합니다.',
  count_of_reviews: '상품에 등록된 리뷰의 개수입니다. 별점 평가 개수와 구별합니다.',
  star_rating: '상품의 평균 별점입니다. 평점 척도와 표시값을 함께 확인합니다.',
  count_of_star_ratings: '상품에 별점을 남긴 평가의 개수입니다. 글로 작성된 리뷰 개수와 다를 수 있습니다.',
  id: '수집 행을 구분하는 관리 식별자입니다. 쇼핑몰 상품 번호와 다른 값입니다.',
  country: '프로젝트에서 사용하는 시장 코드입니다.',
  account_name: '데이터를 수집한 쇼핑몰을 구분하는 값입니다.',
  item: '쇼핑몰에서 상품을 구분하는 식별값입니다. 제조사 모델명과 구별합니다.',
  product_url: '수집한 상품의 상세 페이지 주소입니다.',
  main_rank: 'MAIN 수집 목록에서 상품이 나타난 순서입니다. 쇼핑몰의 정렬 방식도 함께 확인합니다.',
  bsr_rank: 'BSR 수집 목록에서 상품이 나타난 순서입니다. 쇼핑몰의 정렬 방식도 함께 확인합니다.',
  calendar_week: '수집 시점에 해당하는 주차를 나타내는 관리값입니다.',
  crawl_datetime: '상품 데이터를 수집한 시각입니다. 상품 출시일이나 리뷰 작성일이 아닙니다.',
};

function manualCommonKeys(datasets) {
  if (datasets.length < 2) return new Set();
  return new Set(datasets[0].fields.filter(first =>
    Object.hasOwn(manualCommonDefinitions, first.field) &&
    datasets.every(dataset => dataset.fields.some(candidate =>
      candidate.field === first.field && candidate.direct === first.direct
    ))
  ).map(field => field.field));
}

function manualFieldsForScope(datasets, category, scope) {
  const common = manualCommonKeys(datasets);
  const fields = datasets.find(dataset => dataset.category === category)?.fields || [];
  return fields.filter(field => scope === 'common' ? common.has(field.field) : !common.has(field.field));
}

// Keep the original dataset objects as the source for viewing, editing and saving.
// S.c is always a real product; S.scope controls only which fields are listed.
const manualCategoryCodes = {tv: 'TV', ref: 'REF', ldy: 'LDY', ldy_dryer: 'DRYER', dryer: 'DRYER'};
const manualDatasets = () => D.datasets.filter(dataset => dataset.retailer === S.r);
const manualScopedFields = () => manualFieldsForScope(manualDatasets(), S.c, S.scope);
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
const manualDefinition = document.createElement('section');
manualDefinition.className = 'manual-definition';
manualDefinition.id = 'manualDefinition';
document.querySelector('.lessonhead').after(manualDefinition);
const manualExample = document.createElement('section');
manualExample.id = 'manualExample';
manualExample.className = 'manual-example';
manualExample.innerHTML = '<header class="manual-example-head" id="manualExampleHead"></header><div class="manual-example-body"></div>';
manualDefinition.after(manualExample);
manualExample.lastElementChild.append(document.querySelector('.viewer'), $('inspector'));

function normalizeManualScope() {
  const datasets = manualDatasets();
  if (!datasets.some(dataset => dataset.category === S.c)) S.c = datasets[0].category;
  if (S.scope !== 'common') S.scope = S.c;
  if (S.scope === 'common' && !manualCommonKeys(datasets).size) S.scope = S.c;
  const fields = manualScopedFields();
  if (!fields.some(f => f.field === S.field)) {
    S.field = (fields.find(f => f.field === 'retailer_sku_name') || fields[0])?.field || '';
    S.photo = 0;
  }
}

const manualBaseNavigation = navigation;
navigation = function() {
  manualBaseNavigation();
  const datasets = manualDatasets(), common = manualCommonKeys(datasets);
  const scopes = [...(common.size ? ['common'] : []), ...datasets.map(dataset => dataset.category)];
  $('categoryNav').innerHTML = scopes.map(scope => {
    const count = scope === 'common' ? common.size : manualFieldsForScope(datasets, scope, scope).length;
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
    ? manualDatasets().map(dataset => manualCategoryLabel(dataset.category)).join(' · ') + ' 공통 컬럼입니다. 제품군별 예시에서 화면과 확인 방법을 선택하세요.'
    : manualCategoryLabel(S.c) + '의 제품군별 컬럼입니다. 공통 컬럼은 공통 탭에서 확인하세요.';
  $('routeSummary').insertAdjacentHTML('afterbegin', '<strong class="manual-route-product">' + esc(manualCategoryLabel(S.c)) + ' · </strong>');
};

const manualBaseSetField = setField;
setField = function(key) {
  // The all-fields table can jump to a field outside the current scope.
  if (!manualScopedFields().some(f => f.field === key)) {
    S.scope = manualCommonKeys(manualDatasets()).has(key) ? 'common' : S.c;
    S.field = key;
    S.photo = 0;
    render();
  } else manualBaseSetField(key);
};

const manualBaseRenderLesson = renderLesson;
renderLesson = function() {
  const fields = manualScopedFields(), common = S.scope === 'common';
  manualDefinition.hidden = !common || !fields.length;
  manualExample.hidden = !fields.length;
  manualScopeBadge.textContent = common ? '공통 컬럼' : manualCategoryLabel(S.c) + ' 제품군별';
  if (!fields.length) {
    $('lessonTitle').textContent = '제품군별 컬럼이 없습니다.';
    $('lessonCode').textContent = '공통 탭에서 컬럼을 확인하세요.';
    $('lessonNumber').textContent = '–';
    $('prevField').disabled = $('nextField').disabled = true;
    renderEditorStatus();
    return;
  }
  manualBaseRenderLesson();
  const f = field(), index = fields.indexOf(f);
  $('prevField').disabled = index <= 0;
  $('nextField').disabled = index >= fields.length - 1;
  if (common) {
    manualDefinition.innerHTML = '<strong>공통 설명</strong><p>' + esc(manualCommonDefinitions[f.field]) + '</p><div class="manual-product-chips">' +
      manualDatasets().map(dataset => '<span>' + esc(manualCategoryLabel(dataset.category)) + '</span>').join('') + '</div>';
  } else {
    const appliesTo = manualDatasets().filter(dataset => dataset.fields.some(candidate => candidate.field === f.field));
    manualScopeBadge.textContent = appliesTo.length > 1 ? appliesTo.map(dataset => manualCategoryLabel(dataset.category)).join(' · ') + ' 적용' : manualCategoryLabel(S.c) + ' 전용';
  }
  $('manualExampleHead').innerHTML = '<h3>' + (common ? '제품군별 확인 방법' : esc(shortCat[S.c]) + ' 확인 방법') + '</h3>' +
    '<p>' + (common ? '공통 의미는 같아도 화면·예시·주의사항은 제품군마다 다를 수 있습니다.' : '이 제품군의 화면과 수집 기준을 확인하세요.') + '</p>' +
    (common ? '<nav class="manual-example-tabs" aria-label="제품군별 예시">' + manualDatasets().map(dataset =>
      '<button data-example="' + esc(dataset.category) + '" class="' + (S.c === dataset.category ? 'on' : '') + '" aria-pressed="' + (S.c === dataset.category) + '">' +
      esc(manualCategoryLabel(dataset.category)) + (dataset.category === 'tv' ? '' : ' · ' + esc(shortCat[dataset.category])) + '</button>'
    ).join('') + '</nav>' : '') + '<p id="manualEditHint" class="manual-edit-hint"' + (editing ? '' : ' hidden') + '>' + esc(manualCategoryLabel(S.c)) + ' 예시의 문구·이미지를 수정합니다. 다른 제품군의 내용은 각각 수정할 수 있습니다.</p>';
  $('manualExampleHead').querySelectorAll('[data-example]').forEach(button => button.onclick = () => {
    S.c = button.dataset.example;
    S.photo = 0;
    render();
  });
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
  $('editText').textContent = manualCategoryLabel(S.c) + ' · 문구 수정';
  $('editImage').textContent = manualCategoryLabel(S.c) + ' · 이미지 수정';
  if (!manualScopedFields().length) $('editText').disabled = $('editImage').disabled = true;
};

// Appended to the imported editor by scripts/import_dx_manual.py.
const serverMeta = JSON.parse($('guide-meta').textContent);
let serverVersion = serverMeta.version;
const manualApi = '/dx/documents/manual/';
const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

function renderEditorStatus() {
    document.body.classList.toggle('edit-mode', editing);
    $('editorBar').hidden = !editing && revision === downloadedRevision;
    $('editModeToggle').classList.toggle('on', editing);
    $('editModeToggle').setAttribute('aria-pressed', editing);
    $('editModeToggle').textContent = editing ? '편집 종료' : '편집 모드';
    $('undoEdit').disabled = !undoStack.length || saveBusy;
    $('saveGuide').disabled = saveBusy || revision === downloadedRevision;
    $('saveGuide').textContent = saveBusy ? '저장 중…' : '저장 · Ctrl+S';
    $('editStatus').textContent = saveBusy ? '서버에 저장하고 있습니다.'
        : revision !== downloadedRevision ? '저장하지 않은 변경이 있어요.'
        : serverVersion ? '저장됨 · 버전 ' + serverVersion + (serverMeta.created_by ? ' · ' + serverMeta.created_by : '')
        : '최초 등록본';
    $('editStatus').classList.toggle('dirty', revision !== downloadedRevision);
    for (const id of ['editText', 'editImage', 'manualHistory']) $(id).disabled = saveBusy;
}

async function manualRequest(path, options = {}) {
    const response = await fetch(manualApi + path, {
        credentials: 'same-origin', ...options,
        headers: {'X-CSRFToken': csrfToken, ...options.headers}
    });
    if (response.redirected || !response.headers.get('Content-Type')?.includes('application/json')) {
        throw new Error(response.status === 413 ? '파일이 서버의 업로드 제한을 초과했습니다.' : '저장 응답을 확인하지 못했습니다. 로그인 상태와 연결을 확인하세요.');
    }
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '요청을 처리하지 못했습니다. 다시 시도하세요.');
    return result;
}

async function saveManual() {
    if (saveBusy || revision === downloadedRevision) return;
    if ($('imageEditor').open || $('textEditor').open) {
        showToast('수정 창의 적용 버튼을 누른 뒤 저장하세요.');
        return;
    }
    saveBusy = true;
    $('saveFailure').textContent = '';
    renderEditorStatus();
    const snapshotRevision = revision;
    const snapshot = cloneValue(D);
    const uploaded = [];
    try {
        for (const photo of snapshot.photos) {
            if (!photo.customImage?.startsWith('data:image/')) continue;
            const original = photo.customImage;
            const [header, encoded] = original.split(',');
            const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
            const form = new FormData();
            form.append('image', new Blob([bytes], {type: header.slice(5).split(';')[0]}), photo.name);
            const result = await manualRequest('upload/', {method: 'POST', body: form});
            photo.customImage = result.url;
            uploaded.push({name: photo.name, retailer: photo.retailer, category: photo.category, original, url: result.url});
        }
        const result = await manualRequest('save/', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({version: serverVersion, data: snapshot})
        });
        serverVersion = result.version;
        Object.assign(serverMeta, result);
        downloadedRevision = snapshotRevision;
        for (const image of uploaded) {
            const photo = D.photos.find(p => p.name === image.name && p.retailer === image.retailer && p.category === image.category);
            if (photo?.customImage === image.original) photo.customImage = image.url;
        }
        showToast('서버에 저장했습니다. 버전 ' + serverVersion);
    } catch (error) {
        $('saveFailure').textContent = error.message;
        showToast('저장하지 못했습니다. 현재 수정 내용은 화면에 남아 있습니다.');
    } finally {
        saveBusy = false;
        renderEditorStatus();
    }
}

$('saveGuide').onclick = saveManual;
document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        void saveManual();
    }
});
$('manualHistory').onclick = async () => {
    $('historyList').textContent = '이력을 불러오는 중입니다.';
    $('historyDialog').showModal();
    try {
        const result = await manualRequest('history/');
        $('historyList').replaceChildren();
        for (const item of result.revisions) {
            const row = document.createElement('div');
            row.className = 'manual-history-row';
            const description = document.createElement('span');
            description.textContent = item.version === 0 ? '최초 등록본 · 2026-10-19'
                : '버전 ' + item.version + ' · ' + item.created_by + ' · ' + new Date(item.created_at).toLocaleString('ko-KR');
            const button = document.createElement('button');
            button.textContent = '불러오기';
            button.disabled = item.version === serverVersion;
            button.onclick = async () => {
                if (revision !== downloadedRevision && !confirm('저장하지 않은 변경을 버리고 선택한 버전을 불러올까요?')) return;
                button.disabled = true;
                try {
                    const result = await manualRequest('history/?version=' + item.version);
                    for (const key of Object.keys(D)) delete D[key];
                    Object.assign(D, result.data);
                    undoStack.length = 0;
                    changed();
                    selectDataset();
                    $('historyDialog').close();
                    showToast('버전을 불러왔습니다. 저장하면 새 버전으로 등록됩니다.');
                } catch (error) {
                    showToast(error.message);
                    button.disabled = false;
                }
            };
            row.append(description, button);
            $('historyList').append(row);
        }
    } catch (error) {
        $('historyList').textContent = error.message;
    }
};
render();

})();
