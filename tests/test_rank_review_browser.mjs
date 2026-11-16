// Run through ego-browser against tests/rank_review_preview.py's isolated server.
// Exported runner reuses the caller's Page and never launches another browser.
import assert from 'node:assert/strict';

export async function run(page, screenshotPath) {
    await page.click('[data-key="item:95"]');
    await page.waitForSelector('#rm-photo-drop', {state:'visible'});
    await page.selectOption('#rm-review-result', {label:'품절 확인'});
    await page.fill('#rm-memo', '상품 페이지에서 재고 없음 확인 <safe>');
    async function imageEvent(kind, name) {
        await page.evaluate(async ({kind,name}) => {
            const canvas=document.createElement('canvas'); canvas.width=640; canvas.height=240;
            const ctx=canvas.getContext('2d');ctx.fillStyle='#f1f5f9';ctx.fillRect(0,0,640,240);
            ctx.fillStyle='#b91c1c';ctx.font='26px Arial';ctx.fillText('Out of stock - UI test',32,110);
            ctx.fillStyle='#64748b';ctx.font='16px Arial';ctx.fillText(name,32,155);
            const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
            const transfer=new DataTransfer(); transfer.items.add(new File([blob],name,{type:'image/png'}));
            const event=kind==='paste'?new ClipboardEvent('paste',{clipboardData:transfer,bubbles:true,cancelable:true}):new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true});
            document.getElementById('rm-photo-drop').dispatchEvent(event);
        },{kind,name});
    }
    async function save() {
        await page.click('#rm-save');
        await page.waitForSelector('#rm-edit');
        assert.match(await page.evaluate(()=>document.getElementById('rm-review-message').textContent),/저장했습니다/);
    }
    await imageEvent('paste','paste-proof.png');
    await page.waitForFunction(()=>document.querySelectorAll('#rm-photos .rm-photo-card').length===1&&!document.getElementById('rm-save').disabled);
    await save();
    let state=await page.evaluate(()=>({green:document.querySelectorAll('#rm-table-body .absent.rm-reviewed').length,photos:document.querySelectorAll('#rm-photos img').length,readOnly:document.getElementById('rm-memo').disabled,listPhotos:document.querySelectorAll('#rm-table-body img').length}));
    assert.deepEqual(state,{green:2,photos:1,readOnly:true,listPhotos:0});
    await page.click('#rm-close'); await page.reload(); await page.waitForSelector('[data-key="item:95"]');
    await page.click('[data-key="item:95"]');await page.waitForSelector('#rm-edit');
    await page.waitForFunction(()=>document.querySelector('#rm-photos img')?.naturalWidth===640);
    assert.equal(await page.evaluate(()=>document.getElementById('rm-memo').value),'상품 페이지에서 재고 없음 확인 <safe>');
    await page.click('[data-photo="0"]');
    await page.waitForFunction(()=>document.getElementById('rm-photo-image').naturalWidth===640);
    await page.click('#rm-photo-close');await page.click('#rm-edit');
    await imageEvent('drop','drop-proof.png');
    await page.waitForFunction(()=>document.querySelectorAll('#rm-photos img').length===2&&!document.getElementById('rm-save').disabled);
    await save();
    await page.click('#rm-edit');await page.click('[data-delete="0"]');await save();
    assert.equal(await page.evaluate(()=>document.querySelectorAll('#rm-photos img').length),1);
    await page.click('#rm-dialog details summary');
    await page.click('[data-history-photo="1:0"]');
    await page.waitForFunction(()=>document.getElementById('rm-photo-image').naturalWidth===640);
    await page.click('#rm-photo-close');await page.click('#rm-edit');
    await page.fill('#rm-memo','취소할 변경');
    await imageEvent('paste','discard.png');
    await page.waitForFunction(()=>document.querySelectorAll('#rm-photos img').length===2&&!document.getElementById('rm-save').disabled);
    await page.click('#rm-cancel-edit');await page.acceptDialog();
    assert.equal(await page.evaluate(()=>document.querySelectorAll('#rm-photos img').length),1);
    assert.equal(await page.evaluate(()=>document.getElementById('rm-memo').value),'상품 페이지에서 재고 없음 확인 <safe>');
    await page.click('#rm-edit');await page.selectOption('#rm-review-result',{label:'추가 확인 필요'});await save();
    assert.equal(await page.evaluate(()=>document.querySelectorAll('#rm-table-body .absent.rm-reviewed').length),0);
    await page.click('#rm-edit');await page.selectOption('#rm-review-result',{label:'품절 확인'});await save();
    await page.click('#rm-close');await page.click('[data-key="item:30"]');
    await page.waitForSelector('#rm-save',{state:'visible'});
    await page.selectOption('#rm-review-result',{label:'수집 오류 확인'});await page.fill('#rm-memo','사진 없는 확인 기록');await save();
    assert.equal(await page.evaluate(()=>document.querySelectorAll('#rm-photos img').length),0);
    await page.click('#rm-close');await page.click('[data-key="item:95"]');await page.waitForSelector('#rm-edit');
    await page.click('#rm-edit');await page.focus('#rm-photo-drop');
    if(screenshotPath) console.log(await page.screenshot({path:screenshotPath}));
    console.log('PASS: real API paste/drop/save/reload; read/edit; optional photos; image serving/zoom; deletion history; cancel; result colors; no list images.');
}
