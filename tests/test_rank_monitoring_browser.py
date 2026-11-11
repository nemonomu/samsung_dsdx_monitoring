"""Headless UI regression test using local fixtures, without live DB or app writes."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.test import RequestFactory, override_settings
from django.contrib.staticfiles import finders
from playwright.sync_api import sync_playwright, expect
from apps.dx.dx_layer1.rank_monitoring.api import page as render_page
from apps.dx.dx_layer1.rank_monitoring.comparison import compare
from apps.dx.dx_layer1.rank_monitoring.listing import filtered, lightweight
from tests.rank_monitoring_fixtures import DAY, samples

OUT=ROOT/'output/diagnostics/rank-monitoring'
OUT.mkdir(parents=True,exist_ok=True)
raw=samples()
for record in raw:
    if record['item']=='1':
        record['name']='Samsung <img src=x onerror=alert(1)> TV'
reviews={}
errors=[]
posts=[]
pending_once=True


def response(mode):
    data=compare(raw,DAY,samsung=mode=='samsung')
    data.update(country='SEA',product='TV',retailer='Amazon',date=str(DAY),mode=mode,
                basis='날짜별 최신 MAIN 배치',sku_from_master=True,updated_at='2026-11-11T03:00:00Z',review_storage_available=True)
    for p in data['products']:
        p['review_token']='fixture:'+p['key']
        p['review']=reviews.get(p['key'],{'result':'미확인','memo':'','revision':0,'history':[]})
    return data


def html(mode):
    req=RequestFactory().get(f'/dx/layer1/rank/{mode}/SEA/?date={DAY}')
    req.user=SimpleNamespace(is_authenticated=False)
    with patch('apps.dx.dx_layer1.common.context.load_collection_schedules',return_value=[{'check_type':'retail','schedule_type':'daily'}]), override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage'):
        return render_page(req,mode,'SEA').content.decode()


with sync_playwright() as pw:
    browser=pw.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1600,'height':1100})
    page.on('pageerror',lambda error:errors.append(str(error)))
    def handle(route):
        global pending_once
        url=urlparse(route.request.url)
        if '/static/' in url.path:
            path=finders.find(url.path.split('/static/',1)[1])
            if path:
                return route.fulfill(path=path)
            return route.fulfill(status=404,body='')
        if url.path.endswith('/rank/api/data/'):
            if pending_once:
                pending_once=False
                return route.fulfill(status=202,json={'cache_state':{'state':'pending'}})
            params={key:values[0] for key,values in parse_qs(url.query).items()}
            data=response(params.get('mode','all'))
            products=filtered(data['products'],params)
            number=int(params.get('page','1'))
            visible=[lightweight({**p,'fingerprint':p['key']},{p['key']:p['review']['result']}) for p in products[(number-1)*20:number*20]]
            data.update(products=visible,snapshot='fixture-snapshot',
                        pagination={'page':number,'pages':max(1,(len(products)+19)//20),'count':len(products),'page_size':20},
                        cache_state={'state':'fresh','age_seconds':0})
            return route.fulfill(json=data)
        if url.path.endswith('/rank/api/detail/'):
            params={key:values[0] for key,values in parse_qs(url.query).items()}
            assert params['snapshot']=='fixture-snapshot'
            data=next(p for p in response(params.get('mode','all'))['products'] if p['key']==params['key'])
            return route.fulfill(json={**data,'review_storage_available':True})
        if url.path.endswith('/rank/api/export/'):
            assert parse_qs(url.query)['snapshot']==['fixture-snapshot']
            return route.fulfill(content_type='text/csv',body='ITEM,SKU\r\n80,SKU-80\r\n')
        if url.path.endswith('/rank/api/review/'):
            body=route.request.post_data_json;posts.append(body)
            key=body['token'].split('fixture:',1)[1]
            review={'result':body['result'],'memo':body['memo'],'revision':body['revision']+1,
                    'username':'tester','updated_at':'2026-11-11T03:10:00Z','history':[{'result':body['result'],'memo':body['memo'],'username':'tester','at':'2026-11-11T03:10:00Z'}]}
            reviews[key]=review
            return route.fulfill(json={'review':review})
        if '/rank/all/SEA/' in url.path or '/rank/samsung/SEA/' in url.path:
            return route.fulfill(content_type='text/html',body=html('samsung' if '/samsung/' in url.path else 'all'))
        return route.fulfill(status=404,body='fixture endpoint not found')
    page.route('**/*',handle)
    page.goto(f'http://rank.test/dx/layer1/rank/all/SEA/?date={DAY}')
    expect(page.locator('#rm-results')).to_be_visible()
    expect(page.locator('[data-view="all"]')).to_have_attribute('aria-pressed','true')
    expect(page.locator('#rm-table-body tr')).to_have_count(7)
    assert page.locator('#rm-table-body tr').first.locator('td').count()==9
    assert page.locator('#rm-table-body tr').first.locator('td').nth(2).inner_text()=='1'
    assert page.locator('#rm-table-body img').count()==0
    expect(page.locator('#rm-table-body')).to_contain_text('<img src=x onerror=alert(1)>')
    expect(page.locator('#rm-table-head')).to_contain_text('ITEM')
    expect(page.locator('#rm-table-head')).to_contain_text('SKU')
    page.screenshot(path=str(OUT/'all-products.png'),full_page=True)
    page.locator('[data-view="review"]').click()
    expect(page.locator('#rm-table-body tr')).to_have_count(5)
    assert page.locator('#rm-table-body tr').first.locator('td').nth(2).inner_text()=='30'
    page.locator('#rm-search').fill('SKU-80')
    expect(page.locator('#rm-table-body tr')).to_have_count(1)
    expect(page.locator('#rm-table-body .rm-rank.jump')).to_have_count(2)
    page.locator('[data-key="item:80"]').click()
    expect(page.locator('#rm-dialog')).to_be_visible()
    expect(page.locator('#rm-detail')).to_contain_text('SKU-80')
    page.locator('#rm-review-result').select_option('순위 변동 확인')
    page.locator('#rm-memo').fill('상품 페이지 및 수집 로그 확인 <safe>')
    page.locator('#rm-save').click()
    expect(page.locator('#rm-review-message')).to_contain_text('저장했습니다')
    assert posts[0]['revision']==0
    assert page.locator('#rm-history safe').count()==0
    page.screenshot(path=str(OUT/'review-dialog.png'),full_page=True)
    page.locator('#rm-close').click()
    with page.expect_download() as download:
        page.locator('#rm-export').click()
    assert download.value.suggested_filename=='rank-export.csv'
    page.locator('#rm-search').fill('')
    page.locator('[data-signal="return"]').click()
    expect(page.locator('#rm-table-body tr')).to_have_count(1)
    page.locator('[data-view="all"]').click()
    expect(page.locator('#rm-table-body tr')).to_have_count(7)
    page.locator('#rm-product').select_option('REF')
    expect(page.locator('#rm-results')).to_be_hidden()
    page.goto(f'http://rank.test/dx/layer1/rank/samsung/SEA/?date={DAY}')
    expect(page.locator('#rm-results')).to_be_visible()
    expect(page.locator('[data-view="all"]')).to_have_attribute('aria-pressed','true')
    expect(page.locator('#rm-table-body tr')).to_have_count(6)
    expect(page.locator('#rm-basis')).to_contain_text('삼성 판별')
    page.screenshot(path=str(OUT/'samsung-products.png'),full_page=True)
    page.set_viewport_size({'width':760,'height':1000})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path=str(OUT/'mobile.png'),full_page=True)
    assert not errors,errors
    browser.close()
print('PASS: rendered monitoring shell; all-products default; nine columns; review priority; SKU search; dialog audit save; escaped text; country menus; Samsung scope; responsive layout.')
