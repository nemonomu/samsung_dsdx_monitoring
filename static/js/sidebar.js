/**
 * 공통 사이드바 — initSidebar, toggleSidebarGroup
 * onSubitemClick은 각 레이어 JS에서 정의 (레이어별 동작이 다름)
 */

function initSidebar() {
    var sidebar = document.getElementById('dx-sidebar');
    if (!sidebar) return;
    var storageKey = sidebar.dataset.storageKey || 'dxSidebarCollapsed';

    // localStorage에서 접힌 상태 복원
    if (localStorage.getItem(storageKey) === '1') {
        sidebar.classList.add('collapsed');
    }

    // 접기/펼치기 버튼
    var btn = sidebar.querySelector('.sidebar-collapse-btn');
    if (btn) {
        btn.addEventListener('click', function() {
            var collapsed = sidebar.classList.toggle('collapsed');
            localStorage.setItem(storageKey, collapsed ? '1' : '');
        });
    }
}

function toggleSidebarGroup(rowEl) {
    var group = rowEl.closest('.sidebar-group');
    if (group) group.classList.toggle('expanded');
}

function toggleSidebarSubgroup(buttonEl) {
    var subgroup = buttonEl.closest('.sidebar-subgroup');
    if (!subgroup) return;

    var subgroupList = subgroup.parentElement;
    var willExpand = !subgroup.classList.contains('expanded');

    if (subgroupList) {
        subgroupList.querySelectorAll('.sidebar-subgroup.expanded').forEach(function(item) {
            if (item === subgroup) return;
            item.classList.remove('expanded');
            var otherButton = item.querySelector('.sidebar-subgroup-title');
            var otherChildren = item.querySelector('.sidebar-subgroup-children');
            if (otherButton) otherButton.setAttribute('aria-expanded', 'false');
            if (otherChildren) otherChildren.hidden = true;
        });
    }

    subgroup.classList.toggle('expanded', willExpand);
    buttonEl.setAttribute('aria-expanded', willExpand ? 'true' : 'false');
    var children = subgroup.querySelector('.sidebar-subgroup-children');
    if (children) children.hidden = !willExpand;
}

function setSidebarIssueBadge(target, count) {
    if (!target) return;
    var normalizedCount = Math.max(0, Number(count) || 0);
    var badge = target.querySelector(':scope > .sidebar-issue-badge');

    if (normalizedCount === 0) {
        if (badge) badge.remove();
        return;
    }

    if (!badge) {
        badge = document.createElement('span');
        badge.className = 'sidebar-issue-badge';
        badge.setAttribute('aria-label', '이상치 건수');
        var arrow = target.querySelector(
            ':scope > .sidebar-arrow, :scope > .sidebar-subgroup-arrow'
        );
        target.insertBefore(badge, arrow || null);
    }
    badge.textContent = normalizedCount.toLocaleString();
    badge.title = '이상치 ' + normalizedCount.toLocaleString() + '건';
}

function clearSidebarIssueBadges(groupKeys) {
    (groupKeys || []).forEach(function(groupKey) {
        var group = document.querySelector(
            '.sidebar-group[data-sidebar-group="' + groupKey + '"]'
        );
        if (!group) return;
        group.querySelectorAll('.sidebar-issue-badge').forEach(function(badge) {
            badge.remove();
        });
    });
}

function updateSidebarIssueBadges(groupKey, totalCount, itemCounts) {
    var group = document.querySelector(
        '.sidebar-group[data-sidebar-group="' + groupKey + '"]'
    );
    if (!group) return;

    group.querySelectorAll('.sidebar-issue-badge').forEach(function(badge) {
        badge.remove();
    });
    setSidebarIssueBadge(
        group.querySelector(':scope > .sidebar-item-row'), totalCount
    );

    var sidebarItems = group.querySelectorAll('[data-sidebar-item-name]');
    (itemCounts || []).forEach(function(item) {
        var itemName = String(item.name || '');
        var detailCode = String(item.detailCode || item.detail_code || '');
        sidebarItems.forEach(function(element) {
            var nameMatches = itemName
                && element.dataset.sidebarItemName === itemName;
            var detailMatches = detailCode
                && element.dataset.sidebarDetailCode === detailCode;
            // Product codes take precedence over shared parent/child labels.
            var matches = detailCode
                ? detailMatches || (nameMatches && !element.dataset.sidebarDetailCode
                    && !element.classList.contains('sidebar-subgroup'))
                : nameMatches && !element.dataset.sidebarDetailCode;
            if (!matches) return;

            var target = element.classList.contains('sidebar-subgroup')
                ? element.querySelector(':scope > .sidebar-subgroup-title')
                : element;
            setSidebarIssueBadge(target, item.count);
        });
    });
}

document.addEventListener('DOMContentLoaded', initSidebar);
