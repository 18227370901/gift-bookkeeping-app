
function toggleConnTypeFields(prefix) {
  const isLong = document.getElementById(prefix === 'new' ? 'connTypeLong' : 'editConnTypeLong').checked;
  const longFields = document.getElementById(prefix + 'LongConnFields');
  const urlFields = document.getElementById(prefix + 'WebhookUrlFields');
  const urlInput = document.getElementById(prefix === 'new' ? 'newWebhookUrl' : 'editWebhookUrl');
  const botIdInput = document.getElementById(prefix === 'new' ? 'newBotId' : 'editBotId');
  const botSecretInput = document.getElementById(prefix === 'new' ? 'newBotSecret' : 'editBotSecret');

  if (isLong) {
    longFields.style.display = 'block';
    urlFields.style.display = 'none';
    if (urlInput) urlInput.removeAttribute('required');
    if (botIdInput) botIdInput.setAttribute('required', 'required');
    if (botSecretInput) botSecretInput.setAttribute('required', 'required');
  } else {
    longFields.style.display = 'none';
    urlFields.style.display = 'block';
    if (urlInput) urlInput.setAttribute('required', 'required');
    if (botIdInput) botIdInput.removeAttribute('required');
    if (botSecretInput) botSecretInput.removeAttribute('required');
  }
}

function togglePasswordVisibility(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const icon = btn.querySelector('i');
  if (input.type === 'password') {
    input.type = 'text';
    if (icon) icon.className = 'fa-solid fa-eye-slash';
  } else {
    input.type = 'password';
    if (icon) icon.className = 'fa-solid fa-eye';
  }
}

// 页面矩阵全选/清空
function selectAllPages(prefix) {
  const container = document.getElementById(prefix + 'PageMatrix');
  if (container) {
    container.querySelectorAll('input[type="checkbox"]').forEach(cb => { cb.checked = true; });
  }
}
function clearAllPages(prefix) {
  const container = document.getElementById(prefix + 'PageMatrix');
  if (container) {
    container.querySelectorAll('input[type="checkbox"]').forEach(cb => { cb.checked = false; });
  }
}

// 将页面矩阵中勾选的 checkbox 组装为 notify_pages JSON
// 格式: {"create": [...], "update": [...], "delete": [...], "reminder": [...], "broadcast": [...], "security": [...], "system": [...], "status_change": [...]}
// 简化方案: 选中的页面统一放入所有事件类别下
function assembleNotifyPages(prefix) {
  const container = document.getElementById(prefix + 'PageMatrix');
  if (!container) return '{}';
  const checkedPages = [];
  container.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
    checkedPages.push(cb.value);
  });
  // 如果全部勾选或不勾选，返回空对象 {} 表示不过滤
  if (checkedPages.length === 0 || checkedPages.length === 14) return '{}';
  // 将选中的页面放入各事件类别下
  const categories = ['create', 'update', 'delete', 'reminder', 'broadcast', 'security', 'system', 'status_change'];
  const pagesObj = {};
  categories.forEach(cat => { pagesObj[cat] = checkedPages.slice(); });
  return JSON.stringify(pagesObj);
}

// V7: 在 Modal 顶部显示错误提示横幅（替代浏览器原生气泡）
function showWebhookFormError(errorDivId, message) {
  const errorDiv = document.getElementById(errorDivId);
  const html = `<div class="alert alert-danger alert-dismissible rounded-3 py-2 mb-0"><i class="fa-solid fa-circle-exclamation me-1"></i>${message}<button type="button" class="btn-close ms-2" onclick="this.parentElement.remove()"></button></div>`;
  if (errorDiv) {
    errorDiv.innerHTML = html;
    errorDiv.scrollIntoView({ behavior: 'smooth', block: 'center' });
  } else {
    alert(message);
  }
}

// V7: 保存前显式必填校验（保存只保存、不校验凭证真实性，但必填项必须齐全）
function validateWebhookForm(form, prefix) {
  const missing = [];
  const nameInput = form.querySelector('input[name="name"]');
  if (!nameInput || !nameInput.value.trim()) missing.push('渠道名称');

  const isLong = document.getElementById(prefix === 'new' ? 'connTypeLong' : 'editConnTypeLong').checked;
  if (isLong) {
    const botId = document.getElementById(prefix === 'new' ? 'newBotId' : 'editBotId');
    const botSecret = document.getElementById(prefix === 'new' ? 'newBotSecret' : 'editBotSecret');
    if (!botId || !botId.value.trim()) missing.push('Bot ID');
    if (!botSecret || !botSecret.value.trim()) missing.push('Secret 凭证');
  } else {
    const urlInput = document.getElementById(prefix === 'new' ? 'newWebhookUrl' : 'editWebhookUrl');
    if (!urlInput || !urlInput.value.trim()) missing.push('目标 URL');
  }
  return missing;
}

// V3: AJAX 提交 Webhook 表单，校验失败时在 Modal 内就地显示错误
// V7 新增：
//  - 保存按钮 loading 状态（禁用+转圈）防重复提交；
//  - 保存成功后提示用户用「测试」按钮验证凭证（保存不再校验凭证）
function submitWebhookFormAjax(form, modalId, errorDivId, submitBtn, successTip) {
  const errorDiv = document.getElementById(errorDivId);
  if (errorDiv) errorDiv.innerHTML = '';

  // V7: 按钮置为 loading，防止重复提交
  let origBtnHtml = null;
  if (submitBtn) {
    origBtnHtml = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>正在保存...';
  }

  const formData = new FormData(form);
  fetch(form.action, {
    method: 'POST',
    body: formData,
    headers: { 'X-Requested-With': 'XMLHttpRequest' }
  })
  .then(res => res.json().catch(() => ({ success: false, message: '服务器返回非 JSON 响应' })))
  .then(data => {
    if (data.success) {
      const modalEl = document.getElementById(modalId);
      if (modalEl) {
        const bsModal = bootstrap.Modal.getInstance(modalEl);
        if (bsModal) bsModal.hide();
      }
      // V7: 保存只保存、不校验凭证，提示用「测试」按钮验证连通性
      alert(successTip || data.message || '操作成功');
      location.reload();
    } else {
      showWebhookFormError(errorDivId, data.message || '操作失败');
    }
  })
  .catch(() => {
    showWebhookFormError(errorDivId, '网络请求异常，请稍后重试');
  })
  .finally(() => {
    if (submitBtn && origBtnHtml !== null) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = origBtnHtml;
    }
  });
}

// 初始化新增模态框字段状态
document.addEventListener('DOMContentLoaded', function() {
  toggleConnTypeFields('new');
  onLogFilterChange();


  // 提交前组装 notify_pages JSON - V3: 改为 AJAX 提交
  const newForm = document.getElementById('newWebhookForm');
  if (newForm) {
    newForm.addEventListener('submit', function(e) {
      e.preventDefault();
      document.getElementById('newNotifyPagesHidden').value = assembleNotifyPages('new');
      // V7: 显式必填校验，缺项时在 Modal 顶部明确提示
      const missing = validateWebhookForm(newForm, 'new');
      if (missing.length) {
        showWebhookFormError('newWebhookError', '以下必填项未填写：' + missing.join('、'));
        return;
      }
      submitWebhookFormAjax(newForm, 'newWebhookModal', 'newWebhookError', document.getElementById('newWebhookSubmitBtn'),
        'Webhook 通道已保存。\n\n保存操作不会校验凭证有效性，请点击列表中的「测试」按钮验证连通性。');
    });
  }
  const editForm = document.getElementById('editWebhookForm');
  if (editForm) {
    editForm.addEventListener('submit', function(e) {
      e.preventDefault();
      document.getElementById('editNotifyPagesHidden').value = assembleNotifyPages('edit');
      // V7: 显式必填校验，缺项时在 Modal 顶部明确提示
      const missing = validateWebhookForm(editForm, 'edit');
      if (missing.length) {
        showWebhookFormError('editWebhookError', '以下必填项未填写：' + missing.join('、'));
        return;
      }
      submitWebhookFormAjax(editForm, 'editWebhookModal', 'editWebhookError', document.getElementById('editWebhookSubmitBtn'),
      '修改已保存。\n\n如修改了凭证或地址，请点击列表中的「测试」按钮验证连通性。');
    });
  }

  // 编辑模态框填充
  document.querySelectorAll('.btn-edit-webhook').forEach(btn => {

    btn.addEventListener('click', function() {
      const data = this.dataset;
      const form = document.getElementById('editWebhookForm');
      form.action = '/admin/webhooks/edit/' + data.id;

      document.getElementById('editName').value = data.name || '';
      const isLong = (data.connectionType === 'long_connection');
      document.getElementById('editConnTypeLong').checked = isLong;
      document.getElementById('editConnTypeUrl').checked = !isLong;

      document.getElementById('editBotPlatform').value = data.botPlatform || 'wecom';
      document.getElementById('editBotId').value = data.botId || '';
      document.getElementById('editBotSecret').value = data.botSecret || '';
      document.getElementById('editWebhookUrl').value = data.url || '';
      let extractedChatId = '';
      if (data.url && data.url.indexOf('chatid=') !== -1) {
        extractedChatId = data.url.split('chatid=')[1].split('&')[0];
      }
      document.getElementById('editChatId').value = extractedChatId;
      document.getElementById('editSecret').value = data.secret || '';

      document.getElementById('editNotifyAdd').checked = (data.notifyAdd === '1');
      document.getElementById('editNotifyDelete').checked = (data.notifyDelete === '1');
      document.getElementById('editNotifyReminder').checked = (data.notifyReminder === '1');
      document.getElementById('editNotifyBroadcast').checked = (data.notifyBroadcast === '1');

      // 扩展事件
      document.getElementById('editNotifyUpdate').checked = (data.notifyUpdate === '1');
      document.getElementById('editNotifySecurity').checked = (data.notifySecurity === '1');
      document.getElementById('editNotifySystem').checked = (data.notifySystem === '1');
      document.getElementById('editNotifyStatusChange').checked = (data.notifyStatus === '1');

      // 页面矩阵
      try {
        const pagesData = JSON.parse(data.notifyPages || '{}');
        const allPageKeys = ['ledger','banquets','reminders','reconciliation','recycle_bin','admin_users','admin_logs','admin_broadcasts','admin_webhooks','admin_backups','ai_assistant','ai_config','security','invites'];
        allPageKeys.forEach(pk => {
          const cb = document.getElementById('edit_page_' + pk);
          if (cb) {
            // 如果 pagesData 为空对象 {}，则默认全部勾选
            if (Object.keys(pagesData).length === 0) {
              cb.checked = true;
            } else {
              cb.checked = false;
              // 检查各个事件类别下的页面列表
              for (const cat in pagesData) {
                if (Array.isArray(pagesData[cat]) && pagesData[cat].includes(pk)) {
                  cb.checked = true;
                  break;
                }
              }
            }
          }
        });
      } catch(e) {
        // 解析失败时默认全选
        document.querySelectorAll('#editPageMatrix input[type="checkbox"]').forEach(cb => { cb.checked = true; });
      }

      toggleConnTypeFields('edit');
      const editModal = new bootstrap.Modal(document.getElementById('editWebhookModal'));
      editModal.show();
    });
  });

  // 测试 Webhook 发送（V8: 增加超时保护 + toast 提示替换 alert）
  document.querySelectorAll('.btn-test-webhook').forEach(btn => {
    btn.addEventListener('click', function() {
      const id = this.dataset.id;
      const origHtml = this.innerHTML;
      const btnEl = this;
      btnEl.disabled = true;
      btnEl.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>测试中...';

      // V8: AbortController 前端超时保护（后端已优化为 5s 超时）
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10000);

      // 2 秒内未返回时追加提示，避免"看起来像无反应"
      let slowTimer = null;
      slowTimer = setTimeout(() => {
        showToast('正在等待目标服务器响应，请稍候...', 'info');
      }, 2000);

      fetch('/admin/webhook/test/' + id, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': '""'
        },
        signal: controller.signal
      })
      .then(res => res.json())
      .then(data => {
        if (data.success && (data.code === 200 || data.status_code === 200)) {
          showToast('【测试成功】' + (data.message || 'Webhook / 机器人通道测试响应正常！') + '（状态码 ' + (data.status_code || data.code || 200) + '）', 'success');
          // 局部刷新推送日志表格
          window.location.reload();
        } else {
          showToast('【测试失败】' + (data.message || '连接失败，请检查企业微信机器人凭证或目标地址') + '（状态码 ' + (data.status_code || data.code || '?') + '）', 'danger');
        }
      })
      .catch(err => {
        if (err && err.name === 'AbortError') {
          showToast('测试超时：目标服务器响应超过 10 秒未返回，请检查 Webhook 地址与网络后重试', 'danger');
        } else {
          showToast('请求异常: ' + err, 'danger');
        }
      })
      .finally(() => {
        clearTimeout(timeoutId);
        if (slowTimer) clearTimeout(slowTimer);
        btnEl.disabled = false;
        btnEl.innerHTML = origHtml;
      });
    });
  });
});

// --- Webhook Logs Pagination & Filter Management ---
let currentLogPage = 1;
let currentLogPerPage = 10; // default 10 per page

function getFilteredLogRows() {
  const searchInput = document.getElementById('logSearchInput');
  const query = searchInput ? (searchInput.value || '').toLowerCase().trim() : '';
  const eventFilter = document.getElementById('logEventTypeFilter');
  const eventType = eventFilter ? eventFilter.value : 'all';
  const statusFilterEl = document.getElementById('logStatusFilter');
  const statusFilter = statusFilterEl ? statusFilterEl.value : 'all';
  const allRows = Array.from(document.querySelectorAll('#webhookLogsTbody .log-row'));

  return allRows.filter(row => {
    const searchData = (row.dataset.search || '').toLowerCase();
    const rowEvent = row.dataset.event || '';
    const rowStatus = row.dataset.status || '';

    if (query && !searchData.includes(query)) return false;

    if (eventType !== 'all') {
      if (eventType === 'create' && !['create', 'record_create'].includes(rowEvent)) return false;
      else if (eventType === 'delete' && !['delete', 'record_delete', 'batch_delete'].includes(rowEvent)) return false;
      else if (eventType !== 'create' && eventType !== 'delete' && rowEvent !== eventType) return false;
    }

    if (statusFilter !== 'all' && rowStatus !== statusFilter) return false;

    return true;
  });
}

function renderLogPagination(totalItems, filteredRows) {
  const nav = document.getElementById('logPaginationNav');
  const startSpan = document.getElementById('logPageStart');
  const endSpan = document.getElementById('logPageEnd');
  const totalCountSpan = document.getElementById('logFilteredCount');
  const noMatchRow = document.getElementById('noMatchLogsRow');
  if (!nav || !startSpan || !endSpan || !totalCountSpan) return;

  totalCountSpan.innerText = totalItems;

  const allRows = document.querySelectorAll('#webhookLogsTbody .log-row');
  allRows.forEach(r => r.style.display = 'none');

  if (totalItems === 0) {
    startSpan.innerText = '0';
    endSpan.innerText = '0';
    nav.innerHTML = '';
    if (noMatchRow) noMatchRow.style.display = '';
    return;
  }
  if (noMatchRow) noMatchRow.style.display = 'none';

  let effectivePerPage = (currentLogPerPage === 'all') ? totalItems : parseInt(currentLogPerPage, 10);
  const totalPages = Math.max(1, Math.ceil(totalItems / effectivePerPage));
  if (currentLogPage > totalPages) currentLogPage = totalPages;
  if (currentLogPage < 1) currentLogPage = 1;

  const startIndex = (currentLogPage - 1) * effectivePerPage;
  const endIndex = Math.min(startIndex + effectivePerPage, totalItems);

  startSpan.innerText = startIndex + 1;
  endSpan.innerText = endIndex;

  for (let i = startIndex; i < endIndex; i++) {
    if (filteredRows[i]) {
      filteredRows[i].style.display = '';
    }
  }

  nav.innerHTML = '';
  if (totalPages <= 1) return;

  const prevLi = document.createElement('li');
  prevLi.className = `page-item ${currentLogPage === 1 ? 'disabled' : ''}`;
  prevLi.innerHTML = `<button type="button" class="page-link rounded-2 px-2 shadow-none" onclick="changeLogPage(${currentLogPage - 1})"><i class="fa-solid fa-chevron-left"></i></button>`;
  nav.appendChild(prevLi);

  const maxButtons = 5;
  let startPage = Math.max(1, currentLogPage - 2);
  let endPage = Math.min(totalPages, startPage + maxButtons - 1);
  if (endPage - startPage < maxButtons - 1) {
    startPage = Math.max(1, endPage - maxButtons + 1);
  }

  for (let p = startPage; p <= endPage; p++) {
    const li = document.createElement('li');
    li.className = `page-item ${p === currentLogPage ? 'active' : ''}`;
    li.innerHTML = `<button type="button" class="page-link rounded-2 px-2 shadow-none fw-bold" onclick="changeLogPage(${p})">${p}</button>`;
    nav.appendChild(li);
  }

  const nextLi = document.createElement('li');
  nextLi.className = `page-item ${currentLogPage === totalPages ? 'disabled' : ''}`;
  nextLi.innerHTML = `<button type="button" class="page-link rounded-2 px-2 shadow-none" onclick="changeLogPage(${currentLogPage + 1})"><i class="fa-solid fa-chevron-right"></i></button>`;
  nav.appendChild(nextLi);
}

function changeLogPage(page) {
  currentLogPage = page;
  const filtered = getFilteredLogRows();
  renderLogPagination(filtered.length, filtered);
  updateLogSelection();
}

function onLogFilterChange() {
  currentLogPage = 1;
  const filtered = getFilteredLogRows();
  renderLogPagination(filtered.length, filtered);
  updateLogSelection();
}

function onLogPerPageChange() {
  currentLogPerPage = document.getElementById('logPerPageSelect').value;
  currentLogPage = 1;
  const filtered = getFilteredLogRows();
  renderLogPagination(filtered.length, filtered);
  updateLogSelection();
}

function resetLogFilters() {
  document.getElementById('logSearchInput').value = '';
  document.getElementById('logEventTypeFilter').value = 'all';
  document.getElementById('logStatusFilter').value = 'all';
  document.getElementById('logPerPageSelect').value = '10';
  currentLogPerPage = 10;
  currentLogPage = 1;
  const filtered = getFilteredLogRows();
  renderLogPagination(filtered.length, filtered);
  updateLogSelection();
}

function toggleSelectAllLogs(masterCb) {
  const visibleCheckboxes = Array.from(document.querySelectorAll('#webhookLogsTbody .log-row'))
    .filter(r => r.style.display !== 'none')
    .map(r => r.querySelector('.log-item-checkbox'))
    .filter(cb => !!cb);

  visibleCheckboxes.forEach(cb => {
    cb.checked = masterCb.checked;
  });
  updateLogSelection();
}

function updateLogSelection() {
  const allCheckboxes = Array.from(document.querySelectorAll('.log-item-checkbox'));
  const checked = allCheckboxes.filter(cb => cb.checked);
  const countSpan = document.getElementById('selectedLogsCount');
  const batchBtn = document.getElementById('btnBatchDeleteLogs');
  const masterCb = document.getElementById('selectAllLogs');

  if (countSpan) countSpan.innerText = checked.length;
  if (batchBtn) batchBtn.disabled = (checked.length === 0);

  const visibleCheckboxes = Array.from(document.querySelectorAll('#webhookLogsTbody .log-row'))
    .filter(r => r.style.display !== 'none')
    .map(r => r.querySelector('.log-item-checkbox'))
    .filter(cb => !!cb);

  if (masterCb) {
    if (visibleCheckboxes.length > 0 && visibleCheckboxes.every(cb => cb.checked)) {
      masterCb.checked = true;
      masterCb.indeterminate = false;
    } else if (visibleCheckboxes.some(cb => cb.checked)) {
      masterCb.checked = false;
      masterCb.indeterminate = true;
    } else {
      masterCb.checked = false;
      masterCb.indeterminate = false;
    }
  }
}

function deleteSingleLog(logId) {
  if (!confirm(`确定要永久删除 ID 为 #${logId} 的推送日志吗？`)) return;

  fetch(`/admin/webhook/logs/delete/${logId}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': '""'
    }
  })
  .then(res => res.json())
  .then(data => {
    if (data.code === 200) {
      const row = document.querySelector(`.log-row[data-id="${logId}"]`);
      if (row) row.remove();
      const badge = document.getElementById('totalLogsBadge');
      if (badge) badge.innerText = Math.max(0, parseInt(badge.innerText || '1', 10) - 1);
      onLogFilterChange();
    } else {
      alert('删除失败: ' + (data.message || '系统错误'));
    }
  })
  .catch(err => alert('网络异常: ' + err));
}

function submitBatchDeleteLogs() {
  const checked = Array.from(document.querySelectorAll('.log-item-checkbox:checked'));
  if (checked.length === 0) {
    alert('请先勾选需要删除的推送日志！');
    return;
  }
  const ids = checked.map(cb => parseInt(cb.value, 10));
  if (!confirm(`确定要批量删除已选中的 ${ids.length} 条推送日志吗？删除后不可恢复！`)) return;

  const batchBtn = document.getElementById('btnBatchDeleteLogs');
  const origHtml = batchBtn.innerHTML;
  batchBtn.disabled = true;
  batchBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>删除中...';

  fetch('/admin/webhook/logs/batch_delete', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': '""'
    },
    body: JSON.stringify({ log_ids: ids, csrf_token: '""' })
  })
  .then(res => res.json())
  .then(data => {
    batchBtn.disabled = false;
    batchBtn.innerHTML = origHtml;
    if (data.code === 200) {
      ids.forEach(id => {
        const row = document.querySelector(`.log-row[data-id="${id}"]`);
        if (row) row.remove();
      });
      const badge = document.getElementById('totalLogsBadge');
      if (badge) badge.innerText = Math.max(0, parseInt(badge.innerText || '0', 10) - ids.length);
      onLogFilterChange();
      alert(data.message);
    } else {
      alert('批量删除失败: ' + (data.message || '系统错误'));
    }
  })
  .catch(err => {
    batchBtn.disabled = false;
    batchBtn.innerHTML = origHtml;
    alert('网络异常: ' + err);
  });
}

function submitClearAllLogs() {
  if (!confirm('警告：清空全部日志将彻底删除历史所有 Webhook 推送及交付记录，不可恢复！\n\n确定要清空全部日志吗？')) return;

  fetch('/admin/webhook/logs/clear', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': '""'
    },
    body: JSON.stringify({ csrf_token: '""' })
  })
  .then(res => res.json())
  .then(data => {
    if (data.code === 200) {
      document.querySelectorAll('#webhookLogsTbody .log-row').forEach(r => r.remove());
      const badge = document.getElementById('totalLogsBadge');
      if (badge) badge.innerText = '0';
      onLogFilterChange();
      alert(data.message);
    } else {
      alert('清空失败: ' + (data.message || '系统错误'));
    }
  })
  .catch(err => alert('网络异常: ' + err));
}

// V8: 通用 toast 提示容器 + 函数（全局可用，替换原生 alert 提升反馈体验）
function ensureToastContainer() {
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    container.style.zIndex = '1080';
    document.body.appendChild(container);
  }
  return container;
}

function showToast(message, type) {
  const cls = type === 'success' ? 'text-bg-success' : (type === 'warning' ? 'text-bg-warning' : 'text-bg-danger');
  const container = ensureToastContainer();
  const toastEl = document.createElement('div');
  toastEl.className = 'toast align-items-center border-0 ' + cls;
  toastEl.setAttribute('role', 'alert');
  toastEl.innerHTML = '<div class="d-flex"><div class="toast-body">' + message + '</div>' +
    '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>';
  container.appendChild(toastEl);
  const toast = new bootstrap.Toast(toastEl, { delay: 5000 });
  toast.show();
  toastEl.addEventListener('hidden.bs.toast', function() { toastEl.remove(); });
}

