// Persist selection per retailer / scope / column, independent of array position.
function manualPhotoKey(scope, category, column) {
  return (scope === 'common' ? 'common' : category) + ':' + column;
}
function manualPhotoCandidates(photos, state) {
  return photos.filter(p => p.retailer === state.r && p.category !== 'hhp' &&
    (state.scope === 'common' || p.category === state.c || p.category === 'all') &&
    p.boxes.some(b => b.fields.includes(state.field)));
}
function manualPhotoLegacyOrder(p) {
  const added = /^user_photo_(\d+)$/.exec(p.name);
  return added ? Number(added[1]) : (Date.parse(p.date) || 0);
}
function manualSortPhotos(photos, state) {
  const key = manualPhotoKey(state.scope, state.c, state.field);
  const legacyScore = p => (p.preferredOverview ? 100 : 0) +
    (/capacity|screen_size/.test(state.field) && /사양/.test(p.stage) ? 3 : 0) +
    (p.stage.startsWith('상세') ? 1 : 0);
  const positions = new Map(photos.map((p, i) => [p, i]));
  return [...photos].sort((a, b) =>
    (b.primaryFor?.[key] || 0) - (a.primaryFor?.[key] || 0) ||
    Number(!!b.userEdited) - Number(!!a.userEdited) ||
    (a.userEdited && b.userEdited ? manualPhotoLegacyOrder(b) - manualPhotoLegacyOrder(a) || positions.get(b) - positions.get(a) : 0) ||
    Number(!!a.commonExample) - Number(!!b.commonExample) || legacyScore(b) - legacyScore(a));
}
function manualInitializePhotoPreferences(photos) {
  // Freeze inferred legacy defaults before an edit, so another column is unaffected.
  const groups = new Map();
  const categories = ['tv', 'ref', 'ldy', 'ldy_dryer', 'dryer'];
  for (const p of photos) {
    if (p.category === 'hhp') continue;
    const scopes = ['common', ...(p.category === 'all' ? categories : [p.category])];
    for (const column of new Set(p.boxes.flatMap(b => b.fields))) for (const scope of scopes) {
      const id = JSON.stringify([p.retailer, scope, column]);
      if (!groups.has(id)) groups.set(id, []);
      groups.get(id).push(p);
    }
  }
  for (const [id, candidates] of groups) {
    const [r, scope, field] = JSON.parse(id), state = {r, scope, c:scope, field};
    const key = manualPhotoKey(scope, scope, field);
    if (candidates.some(p => p.primaryFor?.[key])) continue;
    const chosen = manualSortPhotos(candidates, state)[0];
    chosen.primaryFor = {...chosen.primaryFor, [key]:1};
  }
}
function manualMakePrimary(photos, photo, state) {
  const key = manualPhotoKey(state.scope, state.c, state.field);
  const rank = Math.max(0, ...manualPhotoCandidates(photos, state).map(p => p.primaryFor?.[key] || 0)) + 1;
  photo.primaryFor = {...photo.primaryFor, [key]:rank};
}
