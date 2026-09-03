const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const retailerSource = fs.readFileSync(
    'apps/ds/ds_layer2/static/ds_layer2/js/retailer.js', 'utf8'
);

const requestedUrls = [];
const sandbox = {
    console,
    fetch: async url => {
        requestedUrls.push(url);
        return { json: async () => ({ data: [] }) };
    }
};
vm.createContext(sandbox);
vm.runInContext(retailerSource, sandbox);

(async () => {
    await sandbox.fetchAnomalies(
        'amazon_usa', '2026-09-03', 'US', '10:00', '11:00'
    );

    assert.ok(requestedUrls.some(
        url => url.includes('error_type=imageurl_invalid')
    ));
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
