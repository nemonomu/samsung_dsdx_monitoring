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
<link rel="stylesheet" href="{% static 'dx_document/css/manual-guide.css' %}?v=20261021-expand-v2">
<link rel="stylesheet" href="{% static 'dx_document/css/manual-layout.css' %}?v=20261021-expand-v2">
</head><body><form hidden>{% csrf_token %}</form>
'''
    template += body
    template += '''
<dialog id="historyDialog" class="editdialog"><div class="dialoghead"><h2>수정 이력</h2><button class="close" data-close aria-label="닫기">×</button></div><div class="dialogbody"><p>이전 버전을 불러온 후 저장하면 새 버전으로 등록됩니다.</p><div id="historyList"></div></div></dialog>
{{ guide_data|json_script:"guide-data" }}
{{ guide_meta|json_script:"guide-meta" }}
<script src="{% static 'dx_document/js/manual-guide.js' %}?v=20261021-expand-v2"></script>
</body></html>
'''
    (root / 'templates/dx_document/manual_content.html').write_text(template, encoding='utf-8')
    code = re.findall(r'<script>(.*?)</script>', html, re.S)[-1]
    fields_start = code.index('function renderFields()')
    fields_end = code.index('\nfunction svg(', fields_start)
    fields_code = code[fields_start:fields_end]
    fields_code = fields_code.replace('rows=ds().fields.filter', 'rows=manualScopedFields().filter')
    fields_code = fields_code.replace(
        "'<details class=\"fieldgroup\" '+(g!=='수집 관리 · 기타'||q||fs.some(f=>f.field===S.field)?'open':'')+'><summary>'",
        "'<section class=\"fieldgroup\"><h3 class=\"fieldgroup-title\">'",
    ).replace('</summary>', '</h3>').replace('</details>', '</section>')
    if '<details' in fields_code or 'fieldgroup-title' not in fields_code:
        raise ValueError('Source field-list structure changed; review the always-visible groups.')
    code = code[:fields_start] + fields_code + code[fields_end:]
    lesson_anchor = "$('sceneTabs').setAttribute('aria-label','이미지 보기 방식');"
    if code.count(lesson_anchor) != 1:
        raise ValueError('Source lesson structure changed; review the image-free field display.')
    code = code.replace(lesson_anchor, 'if(renderFieldWithoutImage(f,p,photo))return;\n' + lesson_anchor)
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
    code = code.replace('국가 → 리테일러 → 제품군 순으로 선택합니다.', '국가 → 리테일러를 선택하고, 공통 컬럼 또는 제품군별 탭을 선택합니다. 공통 컬럼은 한 곳에서 설명과 여러 캡처를 확인하고 수정합니다.')
    code = code.replace('실제 수집 컬럼 515개 · 24개 제품군 조합.', "등록 쇼핑몰 '+Object.keys(D.profiles).length+'개 · '+D.datasets.filter(d=>d.category!=='all').length+'개 제품군 조합.")
    code = code.replace("D.datasets.filter(d=>d.retailer===r).map(d=>shortCat[d.category])", "D.datasets.filter(d=>d.retailer===r&&d.category!=='all').map(d=>shortCat[d.category])")
    code = code.replace('목록·상세 표본 확인. 일부 가격·리뷰는 냉장고 공통 위치 예시로 구분했습니다.', '각 컬럼에서 등록된 설명과 캡처를 확인하세요. 새로 추가된 컬럼은 설명과 이미지를 등록해 주세요.')
    code = code.replace('허용된 코드·참고 엑셀은 읽기 전용으로 사용했습니다. 프로젝트 및 DB를 변경하지 않았습니다.', '국가·쇼핑몰·컬럼 구성은 등록된 수집 설정을 참고합니다. 매뉴얼 편집은 실제 수집 설정을 변경하지 않습니다.')
    code = code.replace('전체 컬럼 표와 관리값도 그대로 보존되어 있습니다.', '전체 컬럼 표에서도 표시 대상 컬럼을 확인할 수 있습니다. 편집 모드에서 쇼핑몰·컬럼을 추가하고 여러 이미지를 등록한 뒤 저장하세요.')
    code = re.sub(r"const countries=\[.*?\],shortCat=", "const countries=[...new Set(Object.values(D.profiles).map(p=>p.country))].map(n=>[n,({'미국':'US','독일':'DE','스페인':'ES','멕시코':'MX','태국':'TH','브라질':'BR','인도':'IN'})[n]||'']),shortCat=", code, count=1)
    code = code.replace("dryer:'건조기'}", "dryer:'건조기',hhp:'HHP'}")
    code = code.replace("const ds=()=>D.datasets.find(x=>x.retailer===S.r&&x.category===S.c)", "const ds=()=>manualCurrentDataset()")
    code = code.replace("ds().fields[0].field}", "ds().fields[0]?.field||''}")
    entry_start = code.index('const entry=')
    entry_end = code.index('\nfunction photos()', entry_start)
    code = code[:entry_start] + 'const entry=()=>manualEntry();' + code[entry_end:]
    code = code.replace("category:S.c,stage:", "category:S.scope==='common'?'all':S.c,stage:")
    code = code.replace("$('boxFields').innerHTML=ds().fields.map", "$('boxFields').innerHTML=manualAnnotationFields().map")
    code = code.replace("(p.category===d.category||p.category==='all')", "(d.category==='all'||p.category===d.category||p.category==='all')")
    code = code.replace("+' / '+shortCat[S.c];for", "+' / '+(S.scope==='common'?'공통':shortCat[S.c]);for")
    code = code.replace('const shownExample=photo?.sampleValues?.[f.field]??f.example;', 'const infoField=manualDisplayField(f,photo),shownExample=manualShownExample(f,photo);')
    info_start = code.index("$('inspector').innerHTML=")
    info_end = code.index('\n}', info_start)
    info = code[info_start:info_end]
    for name in ('page', 'position', 'original', 'scope', 'note'):
        info = info.replace('esc(f.' + name + ')', 'esc(infoField.' + name + ')')
    code = code[:info_start] + info + code[info_end:]
    code = code.replace("+esc(item.stage)+'</option>'", "+esc((S.scope==='common'?manualCategoryLabel(item.category)+' · ':'')+item.stage)+'</option>'")
    code += '\n' + (root / 'manual_field_info.js').read_text(encoding='utf-8')
    code += '\n' + (root / 'manual_column_groups.js').read_text(encoding='utf-8')
    code += '\n' + (root / 'manual_country_header.js').read_text(encoding='utf-8')
    code += '\n' + (root / 'manual_grouped_view.js').read_text(encoding='utf-8')
    code += '\n' + (root / 'manual_expansion.js').read_text(encoding='utf-8')
    code += '\n' + (root / 'manual_server_adapter.js').read_text(encoding='utf-8')
    code += '\n})();\n'
    (static / 'js/manual-guide.js').write_text(code, encoding='utf-8')
    print(f'Imported {len(data["datasets"])} datasets and {len(data["photos"])} photos')


if __name__ == '__main__':
    build(sys.argv[1])
