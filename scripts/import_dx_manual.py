"""Import the approved standalone editor into versioned application assets.

Usage: python scripts/import_dx_manual.py path/to/shopping_guide_editor.html
The original file is read only. No database is accessed.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import sys


def build(source):
    root = Path(__file__).resolve().parents[1] / 'apps/dx/dx_document'
    html = Path(source).read_text(encoding='utf-8')
    data = json.loads(re.search(r'<script id="guide-data" type="application/json">(.*?)</script>', html, re.S)[1])
    private = root / 'manual_data'
    images = private / 'images'
    images.mkdir(parents=True, exist_ok=True)

    def image_url(value):
        if not value.startswith('data:image/'):
            raise ValueError('Expected embedded raster image')
        header, encoded = value.split(',', 1)
        raw = base64.b64decode(encoded, validate=True)
        digest = hashlib.sha256(raw).hexdigest()
        (images / digest).write_bytes(raw)
        return '/dx/documents/manual/images/' + digest + '/'

    data['assets'] = {name: image_url(value) for name, value in data['assets'].items()}
    for photo in data['photos']:
        if photo.get('customImage'):
            photo['customImage'] = image_url(photo['customImage'])
    (private / 'seed.json').write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    styles = '\n'.join(re.findall(r'<style[^>]*>(.*?)</style>', html, re.S))
    styles = styles.replace('.fieldgroup:not([open]) .fieldbtn', 'details.fieldgroup:not([open]) .fieldbtn')
    static = root / 'static/dx_document'
    (static / 'css/manual-guide.css').write_text(styles, encoding='utf-8')
    body = html.split('<body', 1)[1].split('>', 1)[1].split('<script id="guide-data"', 1)[0]
    # The local file is a saved editor snapshot: remove stale save-status text.
    body = re.sub(r'<span id="editStatus"[^>]*>.*?</span>', '<span id="editStatus" class="editstatus"></span>', body)
    body = body.replace('<button id="saveAsGuide">다른 이름으로 저장</button>', '')
    body = body.replace('<button id="exportCopy">사본 다운로드</button>', '<button id="manualHistory">수정 이력</button>')
    body = re.sub(r'<dialog id="exportDialog".*?</dialog>', '', body, flags=re.S)
    body = body.replace('쇼핑몰 화면 가이드', '컬럼 확인 가이드')
    template = '''{% load static %}
<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>dx 메뉴얼</title>
<link rel="stylesheet" href="{% static 'dx_document/css/manual-guide.css' %}?v=20261021-readable">
<link rel="stylesheet" href="{% static 'dx_document/css/manual-layout.css' %}?v=20261021-readable">
</head><body><form hidden>{% csrf_token %}</form>
'''
    template += body
    template += '''
<dialog id="historyDialog" class="editdialog"><div class="dialoghead"><h2>수정 이력</h2><button class="close" data-close aria-label="닫기">×</button></div><div class="dialogbody"><p>이전 버전을 불러온 후 저장하면 새 버전으로 등록됩니다.</p><div id="historyList"></div></div></dialog>
{{ guide_data|json_script:"guide-data" }}
{{ guide_meta|json_script:"guide-meta" }}
<script src="{% static 'dx_document/js/manual-guide.js' %}?v=20261021-readable"></script>
</body></html>
'''
    (root / 'templates/dx_document/manual_content.html').write_text(template, encoding='utf-8')
    code = re.findall(r'<script>(.*?)</script>', html, re.S)[-1]
    fields_start = code.index('function renderFields()')
    fields_end = code.index('\nfunction svg(', fields_start)
    fields_code = code[fields_start:fields_end]
    fields_code = fields_code.replace(
        "'<details class=\"fieldgroup\" '+(g!=='수집 관리 · 기타'||q||fs.some(f=>f.field===S.field)?'open':'')+'><summary>'",
        "'<section class=\"fieldgroup\"><h3 class=\"fieldgroup-title\">'",
    ).replace('</summary>', '</h3>').replace('</details>', '</section>')
    if '<details' in fields_code or 'fieldgroup-title' not in fields_code:
        raise ValueError('Source field-list structure changed; review the always-visible groups.')
    code = code[:fields_start] + fields_code + code[fields_end:]
    # Keep the original viewing and editing behavior; replace local file persistence.
    start = code.index('function createExportHtml()')
    end = code.index("window.addEventListener('beforeunload'", start)
    code = code[:start] + '\n/* Server persistence is appended below. */\n' + code[end:]
    start = code.index('function renderEditorStatus()')
    end = code.index('\nfunction changed()', start)
    code = code[:start] + code[end:]
    code = code.rsplit('render();', 1)[0]  # initialize after the server adapter
    code = code.replace("'쇼핑몰 가이드 / '", "'dx 메뉴얼 / '")
    code = code.replace('파일에 저장하세요.', '서버에 저장하세요.')
    code = code.replace('이미지와 동작 코드는 로컬 폴더에 포함되어 있습니다.', '변경 내용은 저장 버튼을 눌러 서버에 보관합니다.')
    code = code.replace("+photo.date;", "+esc(photo.date);")
    code += '\n' + (root / 'manual_server_adapter.js').read_text(encoding='utf-8')
    code += '\n})();\n'
    (static / 'js/manual-guide.js').write_text(code, encoding='utf-8')
    print(f'Imported {len(data["datasets"])} datasets and {len(data["photos"])} photos')


if __name__ == '__main__':
    build(sys.argv[1])
