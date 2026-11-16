const assert = require('node:assert/strict');
const {filterProducts,safeUrl,csvCell,tier}=require('../apps/dx/dx_layer1/static/dx_layer1/js/rank-monitoring.js');
const {reviewed,imageUrl}=require('../apps/dx/dx_layer1/static/dx_layer1/js/rank-review.js');
for (const result of ['품절 확인','판매 종료 확인','구매 가능 확인','순위 변동 확인','수집 오류 확인']) assert.equal(reviewed({result}),true);
for (const result of ['미확인','추가 확인 필요','unknown','']) assert.equal(reviewed({result}),false);
assert.equal(reviewed(null),false);
assert.equal(imageUrl('/dx/layer1/rank/api/review/images/12/'),'/dx/layer1/rank/api/review/images/12/');
for (const url of ['javascript:alert(1)','https://example.com/image.png','//example.com/image','data:image/svg+xml,test','/dx/layer1/rank/api/review/images/12/?redirect=1']) assert.equal(imageUrl(url),'');
const products=[
    {item:'A',sku:'SKU-A',name:'Alpha',cells:[{rank:1,state:'ranked'}],status:'stable',review_needed:false,signals:{}},
    {item:'B',sku:'SKU-B',name:'Beta',cells:[{rank:80,state:'ranked'}],status:'swing',review_needed:true,signals:{swing:true}},
    {item:'C',sku:'SKU-C',name:'Gamma',cells:[{rank:30,state:'ranked'}],status:'return',review_needed:true,signals:{return:true}},
];
const state={view:'all',sort:'rank',signal:'all',tier:'all',query:''};
assert.deepEqual(filterProducts(products,state).map(p=>p.item),['A','C','B']);
assert.deepEqual(filterProducts(products,{...state,view:'review',sort:'priority'}).map(p=>p.item),['C','B']);
assert.deepEqual(filterProducts(products,{...state,query:'sku-b'}).map(p=>p.item),['B']);
assert.equal(filterProducts(products,{...state,tier:'1'}).length,0);
assert.equal(filterProducts(products,{...state,signal:'swing'})[0].item,'B');
assert.equal(safeUrl('javascript:alert(1)'), '');assert.equal(safeUrl('data:text/html,test'),'');
assert.equal(safeUrl('https://example.com/product'),'https://example.com/product');
assert.equal(csvCell('=1+1'),'"\'=1+1"');assert.equal(csvCell('text"quote'),'"text""quote"');
assert.equal(tier(100),0);assert.equal(tier(101),1);assert.equal(tier(300),2);assert.equal(tier(301),-1);
console.log('Rank filters, priority, ITEM/SKU search, safe URLs and CSV export passed.');
