/**
 * 表格列宽手动拖拽调整（V10.11.7）
 * ============================================================
 * 使用方式：
 *   1. 表格标记：<table data-resizable="表格唯一ID">
 *   2. 列标记：所有 <th data-col="列唯一key">（必填，列增减不错位的关键）
 *   3. 可选约束：<th data-col-min="40" data-col-max="200">（默认 min 60 / max 480）
 *   4. JS 动态生成的表格：渲染完成后调用 window.TableResizer.init(table元素)
 *
 * 核心机制：
 *   - 首次进入把各列「自然宽度」固化为显式像素 + table-layout: fixed，使拖拽实时生效
 *   - 每列 th 右缘注入 8px 命中分隔条（Pointer Events，鼠标/触摸统一）
 *   - 拖动过程 body 加 col-resizing 类：user-select:none 防误选表头文字
 *   - 总宽超容器时由 .table-responsive 出横向滚动条，不压缩其他列
 *   - 双击分隔条：自动适应该列内容最大宽度（同帧切换布局测量，无闪烁）
 *   - 持久化：localStorage 键 gift_colw_{用户ID}_{表格ID}，按「用户+表格」隔离
 *   - 重置入口：容器右上角自动注入「重置列宽」小按钮，清除存储恢复默认
 *     V10.11.23：注入点优先取模块级作用域容器 .colw-scope 内的 .colw-header-actions 槽位，
 *     同一卡片多张表格时重置按钮各归各模块；无作用域容器则回退卡片头逻辑（兼容存量页面）
 *   - 可见性感知（V10.11.23）：隐藏容器（隐藏 Tab/折叠区）中的表格延迟初始化——隐藏时
 *     测量宽度为 0 会导致列宽固化异常、分隔条无法拖拽；首次可见时（IntersectionObserver）
 *     再执行正常初始化；老浏览器降级监听 Bootstrap shown 事件统一补扫
 *   - 响应式降级：屏宽 < 768px 不启用（不拖拽、不恢复存储、自然布局）
 */
(function () {
    'use strict';

    // ===== 配置 =====
    var DEFAULT_MIN = 60;   // 默认最小列宽 px
    var DEFAULT_MAX = 480;  // 默认最大列宽 px
    var MOBILE_MAX = 767.98; // 降级断点（与 Bootstrap md 一致）
    var STORAGE_PREFIX = 'gift_colw_';

    // ===== 工具 =====
    function getUserId() {
        var body = document.body;
        return (body && body.dataset && body.dataset.userId) ? body.dataset.userId : '0';
    }

    function storageKey(tableId) {
        return STORAGE_PREFIX + getUserId() + '_' + tableId;
    }

    function isMobile() {
        return window.innerWidth < MOBILE_MAX || window.matchMedia('(pointer: coarse) and (max-width: 767.98px)').matches;
    }

    // ===== 可见性感知（V10.11.23） =====
    function isVisibleTable(table) {
        if (!table || !table.isConnected) return false;
        // display:none 的元素 getClientRects() 为空列表（标准判定）；同时排除 0 尺寸场景
        if (table.getClientRects && table.getClientRects().length === 0) return false;
        var rect = table.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    // 兜底补扫：老浏览器（无 IntersectionObserver）在 Bootstrap 展开/切换事件后统一扫描未初始化表格
    function retryPendingTables() {
        document.querySelectorAll('table[data-resizable]').forEach(function (t) {
            if (!t.__colwInit && isVisibleTable(t)) {
                t.__colwPending = false;
                initTable(t);
            }
        });
    }

    // 不可见表格挂可见性监听：首次真正可见时执行正常初始化（期间不设幂等标记）
    function watchVisibility(table) {
        if (table.__colwObserver || table.__colwPending) return;   // 防重复挂监听
        if ('IntersectionObserver' in window) {
            var ob = new IntersectionObserver(function (entries) {
                for (var i = 0; i < entries.length; i++) {
                    if (entries[i].isIntersecting) {
                        ob.disconnect();
                        table.__colwObserver = null;
                        initTable(table);
                        break;
                    }
                }
            }, { threshold: 0.01 });
            ob.observe(table);
            table.__colwObserver = ob;
        } else {
            table.__colwPending = true;
            document.addEventListener('shown.bs.tab', retryPendingTables);
            document.addEventListener('shown.bs.collapse', retryPendingTables);
            document.addEventListener('shown.bs.modal', retryPendingTables);
        }
    }

    // ===== 单表控制器 =====
    function initTable(table) {
        if (!table || table.__colwInit) return;            // 幂等
        var tableId = table.getAttribute('data-resizable');
        if (!tableId) return;

        // V10.11.23 可见性感知：隐藏容器中的表格不初始化（隐藏时测宽为 0 会导致列宽固化
        // 异常、分隔条无法拖拽），待首次可见时再执行；可见后不再进入此分支
        if (!isVisibleTable(table)) {
            watchVisibility(table);
            return;
        }

        var headRow = table.querySelector('thead tr');
        if (!headRow) return;
        var ths = Array.prototype.slice.call(headRow.querySelectorAll('th[data-col]'));
        if (ths.length === 0) return;

        // 移动端降级：不启用拖拽，保持自然布局
        if (isMobile()) {
            teardown(table);
            return;
        }

        table.__colwInit = true;
        table.__colwId = tableId;

        // 1) 固化各列初始自然宽度（auto 布局下测量），作为「默认宽度」
        var defaults = {};
        ths.forEach(function (th) {
            var col = th.getAttribute('data-col');
            defaults[col] = Math.round(th.getBoundingClientRect().width);
        });
        table.__colwDefaults = defaults;

        // 2) 应用持久化的用户列宽（无记录则保持默认）
        applyStored(table, ths);

        // 3) 切换 fixed 布局 + 单行截断样式（CSS 配合）
        table.style.tableLayout = 'fixed';
        table.classList.add('colw-fixed');
        syncTableWidth(table);

        // 4) 注入分隔条与重置按钮
        ths.forEach(function (th) { attachResizer(table, th); });
        injectResetBtn(table);

        // 5) 截断单元格补 title 提示（hover 看全文）
        refreshCellTitles(table);
    }

    function syncTableWidth(table) {
        if (!table) return;
        var headRow = table.querySelector('thead tr');
        if (!headRow) return;
        var ths = headRow.querySelectorAll('th[data-col]');
        var total = 0;
        ths.forEach(function (th) {
            var w = parseFloat(th.style.width) || th.getBoundingClientRect().width;
            total += w;
        });
        var wrap = table.closest('.table-responsive') || table.parentElement;
        var wrapW = wrap ? wrap.clientWidth : 0;
        var targetW = Math.max(total, wrapW);
        table.style.width = targetW + 'px';
        table.style.minWidth = targetW + 'px';
    }

    function applyStored(table, ths) {
        var key = storageKey(table.__colwId || table.getAttribute('data-resizable'));
        var saved = null;
        try { saved = JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) { saved = null; }
        ths.forEach(function (th) {
            var col = th.getAttribute('data-col');
            var w = (saved && saved[col]) ? saved[col] : (table.__colwDefaults ? table.__colwDefaults[col] : th.getBoundingClientRect().width);
            th.style.width = clampCol(th, w) + 'px';
        });
        syncTableWidth(table);
    }

    function colMin(th) {
        var v = parseFloat(th.getAttribute('data-col-min'));
        return isNaN(v) ? DEFAULT_MIN : v;
    }

    function colMax(th) {
        var v = parseFloat(th.getAttribute('data-col-max'));
        return isNaN(v) ? DEFAULT_MAX : v;
    }

    function clampCol(th, w) {
        var mn = colMin(th), mx = colMax(th);
        return Math.max(mn, Math.min(mx, w));
    }

    function attachResizer(table, th) {
        if (th.querySelector('.colw-resizer')) return;
        var bar = document.createElement('div');
        bar.className = 'colw-resizer';
        bar.title = '拖动调整列宽；双击自动适应内容宽度';
        th.appendChild(bar);

        // ---- 拖拽（Pointer Events：鼠标/触摸统一）----
        bar.addEventListener('pointerdown', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var startX = e.clientX;
            var startW = th.getBoundingClientRect().width;
            bar.setPointerCapture(e.pointerId);
            document.body.classList.add('colw-resizing');

            function onMove(ev) {
                var w = clampCol(th, startW + (ev.clientX - startX));
                th.style.width = w + 'px';
                syncTableWidth(table);
            }
            function onUp() {
                bar.removeEventListener('pointermove', onMove);
                bar.removeEventListener('pointerup', onUp);
                bar.removeEventListener('pointercancel', onUp);
                document.body.classList.remove('colw-resizing');
                syncTableWidth(table);
                saveWidths(table);
                refreshCellTitles(table);
            }
            bar.addEventListener('pointermove', onMove);
            bar.addEventListener('pointerup', onUp);
            bar.addEventListener('pointercancel', onUp);
        });

        // ---- 双击：自动适应内容宽度 ----
        bar.addEventListener('dblclick', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var w = measureContentWidth(table, th);
            th.style.width = clampCol(th, w) + 'px';
            syncTableWidth(table);
            saveWidths(table);
            refreshCellTitles(table);
        });
    }

    // 同帧内切 auto 布局测该列内容自然最大宽，再切回 fixed（一帧内完成，无闪烁）
    function measureContentWidth(table, th) {
        var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
        var cells = Array.prototype.slice.call(table.querySelectorAll('tbody tr'))
            .map(function (tr) { return tr.cells[idx]; })
            .filter(Boolean);
        // 兜底：至少用表头自身
        if (!cells.length) cells = [th];

        table.style.tableLayout = 'auto';
        table.classList.remove('colw-fixed');
        // 该列全部单元格临时放开宽度限制
        var old = cells.map(function (c) { return c.style.width; });
        cells.forEach(function (c) { c.style.width = 'auto'; });
        var maxW = 0;
        cells.forEach(function (c) { maxW = Math.max(maxW, c.scrollWidth); });
        maxW = Math.max(maxW, th.scrollWidth);
        // 恢复
        cells.forEach(function (c, i) { c.style.width = old[i]; });
        table.style.tableLayout = 'fixed';
        table.classList.add('colw-fixed');
        // 加一点余量，防止 ellipsis 恰好贴边
        return maxW + 16;
    }

    // 截断单元格 hover title 提示（初始化 / 拖拽后刷新）
    function refreshCellTitles(table) {
        var headRow = table.querySelector('thead tr');
        if (!headRow) return;
        var ths = Array.prototype.slice.call(headRow.querySelectorAll('th[data-col]'));
        ths.forEach(function (th, colIdx) {
            var rows = table.querySelectorAll('tbody tr');
            Array.prototype.forEach.call(rows, function (tr) {
                var td = tr.cells[colIdx];
                if (!td) return;
                var txt = (td.innerText || '').trim();
                // 内容实际超出可视宽度才需要 title
                if (txt && td.scrollWidth > td.clientWidth + 2) {
                    td.title = txt;
                } else {
                    td.removeAttribute('title');
                }
            });
        });
    }

    function saveWidths(table) {
        var headRow = table.querySelector('thead tr');
        if (!headRow) return;
        var data = {};
        headRow.querySelectorAll('th[data-col]').forEach(function (th) {
            var col = th.getAttribute('data-col');
            data[col] = Math.round(parseFloat(th.style.width) || th.getBoundingClientRect().width);
        });
        try {
            localStorage.setItem(storageKey(table.__colwId), JSON.stringify(data));
        } catch (e) { /* 存储满等异常静默，不影响功能 */ }
    }

    // 注入「重置列宽」按钮（优雅置于卡片标题栏右侧或独立工具条，绝不遮挡操作列表头）
    // V10.11.23：优先挂载到模块级作用域容器 .colw-scope 内的 .colw-header-actions 槽位——
    // 解决「同一卡片内多张表格（如告警操作授权表与推送日志表）重复注入两个按钮」的缺陷；
    // 无作用域容器时回退原有卡片头逻辑，存量页面行为零变化
    function injectResetBtn(table) {
        var wrap = table.closest('.table-responsive') || table.parentElement;
        if (!wrap) return;

        var tid = table.__colwId || 'default';
        if (document.querySelector('.colw-reset-btn[data-table="' + tid + '"]')) return;

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-outline-secondary btn-sm colw-reset-btn ms-2';
        btn.setAttribute('data-table', tid);
        btn.innerHTML = '<i class="fa-solid fa-rotate-left me-1"></i>重置列宽';
        btn.title = '清除已保存的列宽，恢复默认布局';
        btn.addEventListener('click', function () {
            try { localStorage.removeItem(storageKey(table.__colwId)); } catch (e) {}
            var headRow = table.querySelector('thead tr');
            if (headRow && table.__colwDefaults) {
                headRow.querySelectorAll('th[data-col]').forEach(function (th) {
                    var col = th.getAttribute('data-col');
                    th.style.width = clampCol(th, table.__colwDefaults[col]) + 'px';
                });
            }
            syncTableWidth(table);
            refreshCellTitles(table);
        });

        // 优先：模块级作用域槽位（同卡片多表时重置按钮各归各模块）
        var scope = table.closest('.colw-scope');
        if (scope) {
            var scopeBox = scope.querySelector('.colw-header-actions');
            if (scopeBox) {
                scopeBox.appendChild(btn);
                return;
            }
        }

        // 回退：卡片头逻辑（存量页面）
        var card = table.closest('.card');
        var cardHeader = card ? card.querySelector('.card-header') : null;
        if (cardHeader) {
            var targetBox = cardHeader.querySelector('.colw-header-actions') || cardHeader.querySelector('.d-flex.gap-2');
            if (targetBox) {
                targetBox.appendChild(btn);
            } else {
                cardHeader.appendChild(btn);
            }
        } else {
            var bar = document.createElement('div');
            bar.className = 'd-flex justify-content-end p-1 colw-bar mb-1';
            bar.appendChild(btn);
            wrap.parentNode.insertBefore(bar, wrap);
        }
    }

    // ===== 降级清理（移动端）=====
    function teardown(table) {
        if (!table) return;
        table.__colwInit = false;
        // V10.11.23：同步清理可见性监听，避免降级后残留 observer
        if (table.__colwObserver) {
            try { table.__colwObserver.disconnect(); } catch (e) {}
            table.__colwObserver = null;
        }
        table.style.removeProperty('table-layout');
        table.style.removeProperty('width');
        table.style.removeProperty('min-width');
        table.classList.remove('colw-fixed');
        table.querySelectorAll('.colw-resizer').forEach(function (b) { b.remove(); });
        var tid = table.__colwId || 'default';
        var existingBtn = document.querySelector('.colw-reset-btn[data-table="' + tid + '"]');
        if (existingBtn) existingBtn.remove();
        var wrap = table.closest('.table-responsive') || table.parentElement;
        if (wrap) {
            wrap.classList.remove('colw-wrap');
        }
        var headRow = table.querySelector('thead tr');
        if (headRow) {
            headRow.querySelectorAll('th[data-col]').forEach(function (th) {
                th.style.removeProperty('width');
            });
        }
    }

    // ===== 对外 API =====
    var TableResizer = {
        // 初始化单张表格（动态生成的表格在渲染后手动调用）
        init: function (table) { initTable(table); },
        // 全页扫描
        initAll: function () {
            document.querySelectorAll('table[data-resizable]').forEach(initTable);
        },
        // 视口跨越断点时重新适配
        rebind: function () {
            document.querySelectorAll('table[data-resizable]').forEach(function (t) {
                if (isMobile()) { teardown(t); }
                else { initTable(t); }
            });
        }
    };
    window.TableResizer = TableResizer;

    // ===== 启动 =====
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { TableResizer.initAll(); });
    } else {
        TableResizer.initAll();
    }
    // 视口在移动/桌面之间切换时自动启用/降级（防抖）
    var resizeTimer = null;
    window.addEventListener('resize', function () {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function () { TableResizer.rebind(); }, 200);
    });
})();
