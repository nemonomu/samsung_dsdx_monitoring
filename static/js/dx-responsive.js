function initDxMenu(selector) {
    const toggle = document.querySelector(selector);
    if (!toggle) return;

    const panel = document.getElementById(toggle.getAttribute('aria-controls'));
    toggle.hidden = false;
    toggle.addEventListener('click', () => {
        toggle.setAttribute('aria-expanded', String(toggle.getAttribute('aria-expanded') !== 'true'));
    });
    panel.addEventListener('keydown', event => {
        if (event.key === 'Escape' && toggle.getClientRects().length) {
            toggle.setAttribute('aria-expanded', 'false');
            toggle.focus();
        }
    });
}

initDxMenu('.nav-menu-toggle');
initDxMenu('.sidebar-mobile-toggle');

const dxLayerMenu = document.getElementById('layer-navigation');
if (dxLayerMenu) {
    const search = dxLayerMenu.querySelector('.sidebar-search');
    const input = search.querySelector('input');
    const noResults = search.querySelector('.sidebar-no-results');
    search.hidden = false;

    input.addEventListener('input', () => {
        const words = input.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
        const searching = words.length > 0;
        dxLayerMenu.classList.toggle('sidebar-searching', searching);
        let found = false;
        for (const item of dxLayerMenu.querySelectorAll('.sidebar-item, .sidebar-subitem')) {
            const subgroup = item.closest('.sidebar-subgroup');
            const group = item.closest('.sidebar-group');
            const labels = [
                group?.querySelector('.sidebar-item-row .sidebar-text')?.textContent,
                subgroup?.querySelector('.sidebar-subgroup-title')?.textContent,
                item.textContent
            ].join(' ').toLocaleLowerCase();
            const match = searching && words.every(word => labels.includes(word));
            item.toggleAttribute('data-menu-match', match);
            found ||= match;
        }
        for (const button of dxLayerMenu.querySelectorAll('.sidebar-item-row, .sidebar-subgroup-title')) {
            const group = button.parentElement;
            button.disabled = searching;
            button.setAttribute('aria-expanded', String(searching
                ? Boolean(group.querySelector('[data-menu-match]')) : group.classList.contains('expanded')));
        }
        noResults.hidden = !searching || found;
    });

    window.matchMedia('(max-width: 1050px)').addEventListener('change', event => {
        if (!event.matches && input.value) {
            input.value = '';
            input.dispatchEvent(new Event('input'));
        }
    });
}
