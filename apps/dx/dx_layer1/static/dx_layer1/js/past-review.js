(function () {
    'use strict';
    const form = document.getElementById('past-review-filters');
    if (!form) return;
    const catalog = JSON.parse(document.getElementById('l1-column-alert-catalog').textContent);
    const country = document.getElementById('past-review-country');
    const product = document.getElementById('past-review-product');
    const retailer = document.getElementById('past-review-retailer');
    const names = {SEA:'미국', SEG:'독일', SEIB:'스페인', SEM:'멕시코', TSE:'태국', SEDA:'브라질', SIEL:'인도'};
    function options(select, values, title, labels = {}) {
        const previous = select.value;
        select.replaceChildren(new Option(title, ''));
        [...new Set(values)].sort().forEach(value => select.add(new Option(labels[value] ? labels[value]+' · '+value : value, value)));
        if ([...select.options].some(option => option.value === previous)) select.value = previous;
    }
    function updateRetailers() {
        options(retailer, catalog.filter(row => (!country.value || row.country === country.value) &&
            (!product.value || row.product === product.value)).flatMap(row => row.retailers), '전체 리테일러');
    }
    function updateProducts() {
        options(product, catalog.filter(row => !country.value || row.country === country.value).map(row => row.product), '전체 제품군');
        updateRetailers();
    }
    options(country, catalog.map(row => row.country), '전체 국가', names);
    updateProducts();
    country.addEventListener('change', updateProducts);
    product.addEventListener('change', updateRetailers);
    function load() {
        window.CollectionIssues.load({country:country.value, product:product.value, retailer:retailer.value}, true);
    }
    form.addEventListener('submit', event => {event.preventDefault(); load();});
    load();
})();
