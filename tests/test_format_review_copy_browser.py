"""Real modal focus and HTTP clipboard fallback; all SQL is synthetic."""
import html
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'apps/dx/dx_layer2/static/dx_layer2/js/format-review.js').read_text(encoding='utf-8')
copy_function = source[source.index('    async function copySQL('):source.index('    async function onClick(')]
queries = [
    'SELECT * FROM dx_seg.dx_seg_tv_retail_com\nWHERE id IN (113064)\nORDER BY id;',
    'SELECT * FROM dx_seg.dx_seg_tv_retail_com\n'
    'WHERE account_name = \'Amazon\'\n'
    '  AND inventory_status = \'Hisense 65" TV · 499,96€ <test> 한글\'\nORDER BY id DESC;',
]
fixture = """<!doctype html><meta charset="utf-8"><dialog>""" + ''.join(
    '<div class="fr-query"><div><b>조회 SQL</b><button type="button">SQL 복사</button></div>'
    f'<pre>{html.escape(sql)}</pre></div>' for sql in queries
) + '</dialog><script>function message(value){window.lastMessage=value;}\n' + copy_function + """
document.querySelector('dialog').showModal();
document.querySelectorAll('button').forEach(button=>button.onclick=()=>copySQL(button));
window.copies=[];
const nativeCopy=document.execCommand.bind(document);
document.execCommand = action => {
    const input=document.activeElement;
    const selected=input.value?.slice(input.selectionStart,input.selectionEnd);
    const inside=!!input.closest('dialog');
    const result=nativeCopy(action);
    copies.push({selected,inside,result});
    return result;
};
</script>"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**://monitoring.test/**', lambda route: route.fulfill(
        content_type='text/html', body=fixture))
    for mode in ('http', 'https-unavailable', 'https-denied', 'https-modern'):
        page.goto(('http' if mode == 'http' else 'https') + '://monitoring.test/')
        if mode == 'http':
            assert not page.evaluate('window.isSecureContext')
            assert not page.evaluate('!!navigator.clipboard')
            # Reproduce the old bug: a textarea outside the modal cannot focus.
            assert page.evaluate("""() => {
                const input=document.createElement('textarea');
                document.body.appendChild(input); input.focus(); input.select();
                const blocked=document.activeElement !== input;
                input.remove(); return blocked;
            }""")
        else:
            page.evaluate("""mode => {
                Object.defineProperty(navigator, 'clipboard', {configurable:true,
                    value: mode==='https-unavailable' ? undefined : {
                        writeText: async text => {
                            if(mode==='https-denied')throw new DOMException('Denied','NotAllowedError');
                            copies.push({selected:text,inside:true,result:true});
                        }
                    }});
            }""", mode)
        for index, sql in enumerate(queries):
            block = page.locator('.fr-query').nth(index)
            button = block.locator('button')
            button.click()
            expect(button).to_have_text('복사 완료')
            expect(block.locator('[role=status]')).to_contain_text('복사했습니다')
            assert page.evaluate('copies.at(-1)') == {'selected': sql, 'inside': True, 'result': True}
            expect(button).to_be_focused()
            expect(page.locator('textarea')).to_have_count(0)
    # Failed copy must not claim success, and the same button remains retryable.
    page.goto('http://monitoring.test/')
    page.evaluate("window.realCopy=document.execCommand; document.execCommand=()=>false")
    block = page.locator('.fr-query').first
    block.locator('button').click()
    expect(block.locator('[role=status]')).to_contain_text('실패')
    expect(block.locator('button')).to_have_text('다시 복사')
    expect(page.locator('textarea')).to_have_count(0)
    page.evaluate('document.execCommand=realCopy')
    block.locator('button').click()
    expect(block.locator('button')).to_have_text('복사 완료')
    assert not errors, errors
    browser.close()
print('PASS: modal SQL copy on HTTP, missing/denied Clipboard API, modern API, exact text, failure and retry.')
