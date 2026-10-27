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
    var DEFAULT_MIN = 30;    // 默认最小列宽 px（放宽下限）
    var DEFAULT_MAX = 1200;  // 默认最大列宽 px（大幅放宽上限，让管理员随意向右拉伸）
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

    // ===== 可见性感知与动画完成判定（V10.11.38 加固） =====
    function isVisibleTable(table) {
        if (!table || !table.isConnected) return false;
        // 如果处于 Bootstrap 折叠过渡动画中（.collapsing），尺寸尚未稳定，坚决视为不可见
        if (table.closest('.collapsing')) return false;
        // 如果处于已折叠隐藏的容器中（.collapse 且无 .show），视为不可见
        var collapseParent = table.closest('.collapse');
        if (collapseParent && !collapseParent.classList.contains('show')) return false;
        // display:none 的元素 getClientRects() 为空列表（标准判定）；同时排除 0 尺寸场景
        if (table.getClientRects && table.getClientRects().length === 0) return false;
        var rect = table.getBoundingClientRect();
        return rect.width > 20 && rect.height > 10;
    }

    // 全局补扫：Bootstrap 展开/切换事件（折叠完成、Tab 切换、弹窗展现）后重新检测未初始化或尺寸畸变的表格
    function retryPendingTables() {
        document.querySelectorAll('table[data-resizable]').forEach(function (t) {
            if ((!t.__colwInit || t.__colwMalformed) && isVisibleTable(t)) {
                t.__colwPending = false;
                t.__colwMalformed = false;
                initTable(t, true);
            }
        });
    }

    // 全局永久监听 Bootstrap 动态展开完成事件（解决现代浏览器动画中早产测宽导致尺寸为0的顽疾）
    var _globalBootstrapEventsBound = false;
    function ensureGlobalBootstrapEvents() {
        if (_globalBootstrapEventsBound) return;
        _globalBootstrapEventsBound = true;
        document.addEventListener('shown.bs.collapse', retryPendingTables);
        document.addEventListener('shown.bs.tab', retryPendingTables);
        document.addEventListener('shown.bs.modal', retryPendingTables);
    }

    // 不可见表格挂可见性监听：首次真正可见时执行正常初始化（期间不设幂等标记）
    function watchVisibility(table) {
        ensureGlobalBootstrapEvents();
        if (table.__colwObserver || table.__colwPending) return;   // 防重复挂监听
        if ('IntersectionObserver' in window) {
            var ob = new IntersectionObserver(function (entries) {
                for (var i = 0; i < entries.length; i++) {
                    if (entries[i].isIntersecting) {
                        // 必须确认不在折叠过渡动画中才初始化
                        if (isVisibleTable(table)) {
                            ob.disconnect();
                            table.__colwObserver = null;
                            initTable(table);
                            break;
                        }
                    }
                }
            }, { threshold: 0.1 });
            ob.observe(table);
            table.__colwObserver = ob;
        } else {
            table.__colwPending = true;
        }
    }

    // ===== 单表控制器 =====
    function initTable(table, force) {
        if (!table) return;
        if (force && table.__colwInit) {
            teardown(table);
        }
        if (table.__colwInit) return;            // 幂等
        var tableId = table.getAttribute('data-resizable');
        if (!tableId) return;

        // V10.11.38 可见性感知：隐藏或动画中容器中的表格不初始化（隐藏或动画时测宽会导致列宽为0
        // 且重置列宽失效），待动画完全结束并真正稳定可见后再执行
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

        // 零宽与畸变尺寸防御（Zero-Width Guard）：
        // 在 auto 布局测量下，如果任意关键列宽 <= 10px，说明宿主尚未渲染排版完毕，拒绝固化错误尺寸
        var hasMalformedCol = false;
        var defaults = {};
        for (var idx = 0; idx < ths.length; idx++) {
            var th = ths[idx];
            var col = th.getAttribute('data-col');
            var w = Math.round(th.getBoundingClientRect().width);
            if (w <= 10) {
                hasMalformedCol = true;
                break;
            }
            defaults[col] = w;
        }
        if (hasMalformedCol) {
            table.__colwMalformed = true;
            watchVisibility(table);
            return;
        }

        table.__colwInit = true;
        table.__colwMalformed = false;
        table.__colwId = tableId;
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

    function syncTableWidth(table, isDragging) {
        if (!table) return;
        var headRow = table.querySelector('thead tr');
        if (!headRow) return;
        var ths = headRow.querySelectorAll('th[data-col]');
        var total = 0;
        ths.forEach(function (th) {
            var w = parseFloat(th.style.width) || th.getBoundingClientRect().width;
            total += w;
        });
        total = Math.round(total);
        var wrap = table.closest('.table-responsive') || table.parentElement;
        var wrapW = wrap ? wrap.clientWidth : 0;
        
        // 关键重构：拖拽调整时以用户实际设定的各列总宽为准（允许收窄或向右无限延伸）
        // 仅在初始未拖动且总宽小于容器时铺满容器
        var targetW = isDragging ? total : Math.max(total, wrapW);
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
        return isNaN(v) ? DEFAULT_MIN : Math.max(24, Math.min(v, DEFAULT_MIN));
    }

    function colMax(th) {
        var v = parseFloat(th.getAttribute('data-col-max'));
        // 如果 HTML 声明了极小的 max（如 60/120），拖拽时放开到至少 800px，让用户真正拥有调整自由
        return isNaN(v) ? DEFAULT_MAX : Math.max(v, 900);
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

        // ---- 全局窗体级高性能 Pointer 事件（零丢失、零卡顿、任意左右拖动）----
        bar.addEventListener('pointerdown', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var startX = e.clientX;
            var startW = Math.round(th.getBoundingClientRect().width);
            document.body.classList.add('colw-resizing');

            var pendingWidth = startW;
            var rafId = null;

            function onGlobalMove(ev) {
                pendingWidth = clampCol(th, startW + (ev.clientX - startX));
                if (!rafId) {
                    rafId = requestAnimationFrame(function () {
                        th.style.width = pendingWidth + 'px';
                        syncTableWidth(table, true);
                        rafId = null;
                    });
                }
            }
            function onGlobalUp(ev) {
                window.removeEventListener('pointermove', onGlobalMove);
                window.removeEventListener('pointerup', onGlobalUp);
                window.removeEventListener('pointercancel', onGlobalUp);
                if (rafId) {
                    cancelAnimationFrame(rafId);
                    rafId = null;
                }
                document.body.classList.remove('colw-resizing');
                th.style.width = pendingWidth + 'px';
                syncTableWidth(table, true);
                saveWidths(table);
                refreshCellTitles(table);
            }
            window.addEventListener('pointermove', onGlobalMove);
            window.addEventListener('pointerup', onGlobalUp);
            window.addEventListener('pointercancel', onGlobalUp);
        });

        // ---- 双击：自动适应内容宽度 ----
        bar.addEventListener('dblclick', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var w = measureContentWidth(table, th);
            th.style.width = clampCol(th, w) + 'px';
            syncTableWidth(table, true);
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

    // 核心重置调度器：清除持久化并让表格原样恢复纯净原生排版
    function executeTableReset(table, btn) {
        if (!table) return;
        var tid = table.__colwId || table.getAttribute('data-resizable');
        try { localStorage.removeItem(storageKey(tid)); } catch (err) {}
        
        // 显式绿色按钮反馈
        if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-check me-1 text-success"></i>已重置';
            btn.classList.remove('btn-outline-secondary');
            btn.classList.add('btn-outline-success');
            setTimeout(function() {
                btn.innerHTML = '<i class="fa-solid fa-rotate-left me-1"></i>重置列宽';
                btn.classList.remove('btn-outline-success');
                btn.classList.add('btn-outline-secondary');
            }, 1200);
        }

        // 1) 彻底清空所有 th 上的内联定宽
        var headRow = table.querySelector('thead tr');
        if (headRow) {
            headRow.querySelectorAll('th[data-col]').forEach(function (th) {
                th.style.removeProperty('width');
            });
        }
        // 2) 彻底解绑 fixed 布局与一切总宽限制，恢复纯原生流
        table.style.removeProperty('table-layout');
        table.style.removeProperty('width');
        table.style.removeProperty('min-width');
        table.classList.remove('colw-fixed');

        // 3) 移除原有把手，重新测量初始化
        table.querySelectorAll('.colw-resizer').forEach(function(b) { b.remove(); });
        table.__colwInit = false;

        // 延迟一帧等待浏览器重新渲染出自然宽度
        requestAnimationFrame(function () {
            initTable(table, true);
        });
    }

    // 全局事件代理：保障所有重置按钮点击 100% 触发，杜绝内联监听器失效
    document.addEventListener('click', function(e) {
        var resetBtn = e.target.closest('.colw-reset-btn');
        if (!resetBtn) return;
        e.preventDefault();
        e.stopPropagation();
        var tid = resetBtn.getAttribute('data-table');
        var table = document.querySelector('table[data-resizable="' + tid + '"]');
        if (table) {
            executeTableReset(table, resetBtn);
        }
    });

    // 注入「重置列宽」按钮（挂载到操作栏）
    function injectResetBtn(table) {
        var wrap = table.closest('.table-responsive') || table.parentElement;
        if (!wrap) return;

        var tid = table.__colwId || table.getAttribute('data-resizable') || 'default';
        if (document.querySelector('.colw-reset-btn[data-table="' + tid + '"]')) return;

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-outline-secondary btn-sm colw-reset-btn ms-2';
        btn.setAttribute('data-table', tid);
        btn.innerHTML = '<i class="fa-solid fa-rotate-left me-1"></i>重置列宽';
        btn.title = '清除已保存的列宽，恢复默认布局';

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
        // 初始化单张表格（动态生成的表格在渲染后手动调用，支持 force 参数）
        init: function (table, force) { initTable(table, !!force); },
        // 全页扫描
        initAll: function (force) {
            document.querySelectorAll('table[data-resizable]').forEach(function (t) {
                initTable(t, !!force);
            });
        },
        // 视口跨越断点或展开折叠时重新适配
        rebind: function () {
            document.querySelectorAll('table[data-resizable]').forEach(function (t) {
                if (isMobile()) { teardown(t); }
                else { initTable(t, true); }
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
