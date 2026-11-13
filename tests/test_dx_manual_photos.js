// Run: node --test tests/test_dx_manual_photos.js
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync('apps/dx/dx_document/manual_photo_selection.js', 'utf8'), context);
const {manualInitializePhotoPreferences:initialize, manualSortPhotos:sort,
  manualPhotoCandidates:candidates, manualMakePrimary:primary} = context;
const photo = (r, name, fields = ['rank'], category = 'tv') => ({retailer:r, name, category,
  stage:'상세', date:'2026-11-13', userEdited:true, boxes:[{fields}]});
const state = r => ({r, c:'tv', scope:'tv', field:'rank'});
const selected = (photos, s) => sort(candidates(photos, s), s)[0];

test('latest legacy capture wins across every country, without deleting old captures', () => {
  for (const country of ['SEA','SEG','SEIB','SEM','SEDA','SIEL','TSE']) {
    const r = country + '/retailer', s = state(r);
    const old = photo(r,'user_photo_1794545378234');
    old.preferredOverview = true;
    const latest = photo(r,'user_photo_1794545494862');
    latest.stage = '순위 화면에서 수집';
    const photos = [old,latest];
    initialize(photos);
    assert.equal(selected(photos,s),latest);
    assert.equal(photos.length,2);
    assert.equal(selected(JSON.parse(JSON.stringify(photos)),s).name,latest.name);
  }
});

test('explicit representative persists across reload and is isolated by retailer, product and column', () => {
  const r='SEG/expert', s=state(r);
  const old=photo(r,'user_photo_1',['rank','sku']);
  const latest=photo(r,'user_photo_2',['rank','sku']);
  const ref=photo(r,'user_photo_3',['rank'],'ref');
  const other=photo('SEM/expert','user_photo_4');
  const photos=[old,latest,ref,other];
  initialize(photos);
  primary(photos,old,s);
  const reloaded=JSON.parse(JSON.stringify(photos));
  assert.equal(selected(reloaded,s).name,old.name);
  assert.equal(selected(reloaded,{...s,field:'sku'}).name,latest.name);
  assert.equal(selected(reloaded,{...s,c:'ref',scope:'ref'}).name,ref.name);
  assert.equal(selected(reloaded,state('SEM/expert')).name,other.name);
});

test('adding a linked capture only changes the selected column representative', () => {
  const r='TSE/homepro', s=state(r), original=photo(r,'user_photo_1',['rank','sku']);
  const photos=[original];
  initialize(photos);
  const added=photo(r,'user_photo_2',['rank','sku']);
  photos.push(added);
  initialize(photos);
  primary(photos,added,s);
  assert.equal(selected(photos,s),added);
  assert.equal(selected(photos,{...s,field:'sku'}),original);
  assert.equal(selected(photos,{...s,scope:'common'}),original);
});

test('unmodified seed overviews retain their existing priority', () => {
  const data=JSON.parse(fs.readFileSync('apps/dx/dx_document/manual_data/seed.json','utf8'));
  const untouched=data.photos.filter(p=>!p.userEdited);
  const before=new Map();
  for (const p of untouched) for (const f of p.boxes.flatMap(b=>b.fields)) {
    const s={r:p.retailer,c:p.category,scope:p.category,field:f};
    before.set(JSON.stringify(s),selected(untouched,s));
  }
  initialize(untouched);
  for (const [key,p] of before) assert.equal(selected(untouched,JSON.parse(key)),p);
});

test('source modules are included verbatim in the shipped bundle', () => {
  const root='apps/dx/dx_document/';
  const bundle=fs.readFileSync(root+'static/dx_document/js/manual-guide.js','utf8').replace(/\r\n/g,'\n');
  for (const file of ['manual_photo_selection.js','manual_photo_editor.js','manual_expansion.js']) {
    assert.ok(bundle.includes(fs.readFileSync(root+file,'utf8').replace(/\r\n/g,'\n').trim()),file);
  }
});
