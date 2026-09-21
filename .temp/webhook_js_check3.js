
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

// 椤甸潰鐭╅樀鍏ㄩ€?娓呯┖
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

// 灏嗛〉闈㈢煩闃典腑鍕鹃€夌殑 checkbox 缁勮涓?notify_pages JSON
// 鏍煎紡: {"create": [...], "update": [...], "delete": [...], "reminder": [...], "broadcast": [...], "security": [...], "system": [...], "status_change": [...]}
// 绠€鍖栨柟妗? 閫変腑鐨勯〉闈㈢粺涓€鏀惧叆鎵€鏈変簨浠剁被鍒笅
function assembleNotifyPages(prefix) {
  const container = document.getElementById(prefix + 'PageMatrix');
  if (!container) return '{}';
  const checkedPages = [];
  container.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
    checkedPages.push(cb.value);
  });
  // 濡傛灉鍏ㄩ儴鍕鹃€夋垨涓嶅嬀閫夛紝杩斿洖绌哄璞?{} 琛ㄧず涓嶈繃婊?
  if (checkedPages.length === 0 || checkedPages.length === 14) return '{}';
  // 灏嗛€変腑鐨勯〉闈㈡斁鍏ュ悇浜嬩欢绫诲埆涓?
  const categories = ['create', 'update', 'delete', 'reminder', 'broadcast', 'security', 'system', 'status_change'];
  const pagesObj = {};
  categories.forEach(cat => { pagesObj[cat] = checkedPages.slice(); });
  return JSON.stringify(pagesObj);
}

// V7: 鍦?Modal 椤堕儴鏄剧ず閿欒鎻愮ず妯箙锛堟浛浠ｆ祻瑙堝櫒鍘熺敓姘旀场锛?
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

// V7: 淇濆瓨鍓嶆樉寮忓繀濉牎楠岋紙淇濆瓨鍙繚瀛樸€佷笉鏍￠獙鍑瘉鐪熷疄鎬э紝浣嗗繀濉」蹇呴』榻愬叏锛?
function validateWebhookForm(form, prefix) {
  const missing = [];
  const nameInput = form.querySelector('input[name="name"]');
  if (!nameInput || !nameInput.value.trim()) missing.push('娓犻亾鍚嶇О');

  const isLong = document.getElementById(prefix === 'new' ? 'connTypeLong' : 'editConnTypeLong').checked;
  if (isLong) {
    const botId = document.getElementById(prefix === 'new' ? 'newBotId' : 'editBotId');
    const botSecret = document.getElementById(prefix === 'new' ? 'newBotSecret' : 'editBotSecret');
    if (!botId || !botId.value.trim()) missing.push('Bot ID');
    if (!botSecret || !botSecret.value.trim()) missing.push('Secret 鍑瘉');
  } else {
    const urlInput = document.getElementById(prefix === 'new' ? 'newWebhookUrl' : 'editWebhookUrl');
    if (!urlInput || !urlInput.value.trim()) missing.push('鐩爣 URL');
  }
  return missing;
}

// V3: AJAX 鎻愪氦 Webhook 琛ㄥ崟锛屾牎楠屽け璐ユ椂鍦?Modal 鍐呭氨鍦版樉绀洪敊璇?
// V7 鏂板锛?
//  - 淇濆瓨鎸夐挳 loading 鐘舵€侊紙绂佺敤+杞湀锛夐槻閲嶅鎻愪氦锛?
//  - 淇濆瓨鎴愬姛鍚庢彁绀虹敤鎴风敤銆屾祴璇曘€嶆寜閽獙璇佸嚟璇侊紙淇濆瓨涓嶅啀鏍￠獙鍑瘉锛?
function submitWebhookFormAjax(form, modalId, errorDivId, submitBtn, successTip) {
  const errorDiv = document.getElementById(errorDivId);
  if (errorDiv) errorDiv.innerHTML = '';

  // V7: 鎸夐挳缃负 loading锛岄槻姝㈤噸澶嶆彁浜?
  let origBtnHtml = null;
  if (submitBtn) {
    origBtnHtml = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>姝ｅ湪淇濆瓨...';
  }

  const formData = new FormData(form);
  fetch(form.action, {
    method: 'POST',
    body: formData,
    headers: { 'X-Requested-With': 'XMLHttpRequest' }
  })
  .then(res => res.json().catch(() => ({ success: false, message: '鏈嶅姟鍣ㄨ繑鍥為潪 JSON 鍝嶅簲' })))
  .then(data => {
    if (data.success) {
      const modalEl = document.getElementById(modalId);
      if (modalEl) {
        const bsModal = bootstrap.Modal.getInstance(modalEl);
        if (bsModal) bsModal.hide();
      }
      // V7: 淇濆瓨鍙繚瀛樸€佷笉鏍￠獙鍑瘉锛屾彁绀虹敤銆屾祴璇曘€嶆寜閽獙璇佽繛閫氭€?
      alert(successTip || data.message || '鎿嶄綔鎴愬姛');
      location.reload();
    } else {
      showWebhookFormError(errorDivId, data.message || '鎿嶄綔澶辫触');
    }
  })
  .catch(() => {
    showWebhookFormError(errorDivId, '缃戠粶璇锋眰寮傚父锛岃绋嶅悗閲嶈瘯');
  })
  .finally(() => {
    if (submitBtn && origBtnHtml !== null) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = origBtnHtml;
    }
  });
}

// 鍒濆鍖栨柊澧炴ā鎬佹瀛楁鐘舵€?document.addEventListener('DOMContentLoaded', function() {
  toggleConnTypeFields('new');
  onLogFilterChange();


  // 鎻愪氦鍓嶇粍瑁?notify_pages JSON - V3: 鏀逛负 AJAX 鎻愪氦
  const newForm = document.getElementById('newWebhookForm');
  if (newForm) {
    newForm.addEventListener('submit', function(e) {
      e.preventDefault();
      document.getElementById('newNotifyPagesHidden').value = assembleNotifyPages('new');
      // V7: 鏄惧紡蹇呭～鏍￠獙锛岀己椤规椂鍦?Modal 椤堕儴鏄庣‘鎻愮ず
      const missing = validateWebhookForm(newForm, 'new');
      if (missing.length) {
        showWebhookFormError('newWebhookError', '浠ヤ笅蹇呭～椤规湭濉啓锛? + missing.join('銆?));
        return;
      }
      submitWebhookFormAjax(newForm, 'newWebhookModal', 'newWebhookError', document.getElementById('newWebhookSubmitBtn'),
        'Webhook 閫氶亾宸蹭繚瀛樸€俓n\n淇濆瓨鎿嶄綔涓嶄細鏍￠獙鍑瘉鏈夋晥鎬э紝璇风偣鍑诲垪琛ㄤ腑鐨勩€屾祴璇曘€嶆寜閽獙璇佽繛閫氭€с€?);
    });
  }
  const editForm = document.getElementById('editWebhookForm');
  if (editForm) {
    editForm.addEventListener('submit', function(e) {
      e.preventDefault();
      document.getElementById('editNotifyPagesHidden').value = assembleNotifyPages('edit');
      // V7: 鏄惧紡蹇呭～鏍￠獙锛岀己椤规椂鍦?Modal 椤堕儴鏄庣‘鎻愮ず
      const missing = validateWebhookForm(editForm, 'edit');
      if (missing.length) {
        showWebhookFormError('editWebhookError', '浠ヤ笅蹇呭～椤规湭濉啓锛? + missing.join('銆?));
        return;
      }
      submitWebhookFormAjax(editForm, 'editWebhookModal', 'editWebhookError', document.getElementById('editWebhookSubmitBtn'),
      '淇敼宸蹭繚瀛樸€俓n\n濡備慨鏀逛簡鍑瘉鎴栧湴鍧€锛岃鐐瑰嚮鍒楄〃涓殑銆屾祴璇曘€嶆寜閽獙璇佽繛閫氭€с€?);
    });
  }

  // 缂栬緫妯℃€佹濉厖
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

      // 鎵╁睍浜嬩欢
      document.getElementById('editNotifyUpdate').checked = (data.notifyUpdate === '1');
      document.getElementById('editNotifySecurity').checked = (data.notifySecurity === '1');
      document.getElementById('editNotifySystem').checked = (data.notifySystem === '1');
      document.getElementById('editNotifyStatusChange').checked = (data.notifyStatus === '1');

      // 椤甸潰鐭╅樀
      try {
        const pagesData = JSON.parse(data.notifyPages || '{}');
        const allPageKeys = ['ledger','banquets','reminders','reconciliation','recycle_bin','admin_users','admin_logs','admin_broadcasts','admin_webhooks','admin_backups','ai_assistant','ai_config','security','invites'];
        allPageKeys.forEach(pk => {
          const cb = document.getElementById('edit_page_' + pk);
          if (cb) {
            // 濡傛灉 pagesData 涓虹┖瀵硅薄 {}锛屽垯榛樿鍏ㄩ儴鍕鹃€?
            if (Object.keys(pagesData).length === 0) {
              cb.checked = true;
            } else {
              cb.checked = false;
              // 妫€鏌ュ悇涓簨浠剁被鍒笅鐨勯〉闈㈠垪琛?
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
        // 瑙ｆ瀽澶辫触鏃堕粯璁ゅ叏閫?
        document.querySelectorAll('#editPageMatrix input[type="checkbox"]').forEach(cb => { cb.checked = true; });
      }

      toggleConnTypeFields('edit');
      const editModal = new bootstrap.Modal(document.getElementById('editWebhookModal'));
      editModal.show();
    });
  });

  // 娴嬭瘯 Webhook 鍙戦€侊紙V8: 澧炲姞瓒呮椂淇濇姢 + toast 鎻愮ず鏇挎崲 alert锛?
  document.querySelectorAll('.btn-test-webhook').forEach(btn => {
    btn.addEventListener('click', function() {
      const id = this.dataset.id;
      const origHtml = this.innerHTML;
      const btnEl = this;
      btnEl.disabled = true;
      btnEl.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>娴嬭瘯涓?..';

      // V8: AbortController 鍓嶇瓒呮椂淇濇姢锛堝悗绔凡浼樺寲涓?5s 瓒呮椂锛?
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10000);

      // 2 绉掑唴鏈繑鍥炴椂杩藉姞鎻愮ず锛岄伩鍏?鐪嬭捣鏉ュ儚鏃犲弽搴?
      let slowTimer = null;
      slowTimer = setTimeout(() => {
        showToast('姝ｅ湪绛夊緟鐩爣鏈嶅姟鍣ㄥ搷搴旓紝璇风◢鍊?..', 'info');
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
          showToast('銆愭祴璇曟垚鍔熴€? + (data.message || 'Webhook / 鏈哄櫒浜洪€氶亾娴嬭瘯鍝嶅簲姝ｅ父锛?) + '锛堢姸鎬佺爜 ' + (data.status_code || data.code || 200) + '锛?, 'success');
          // 灞€閮ㄥ埛鏂版帹閫佹棩蹇楄〃鏍?
          window.location.reload();
        } else {
          showToast('銆愭祴璇曞け璐ャ€? + (data.message || '杩炴帴澶辫触锛岃妫€鏌ヤ紒涓氬井淇℃満鍣ㄤ汉鍑瘉鎴栫洰鏍囧湴鍧€') + '锛堢姸鎬佺爜 ' + (data.status_code || data.code || '?') + '锛?, 'danger');
        }
      })
      .catch(err => {
        if (err && err.name === 'AbortError') {
          showToast('娴嬭瘯瓒呮椂锛氱洰鏍囨湇鍔″櫒鍝嶅簲瓒呰繃 10 绉掓湭杩斿洖锛岃妫€鏌?Webhook 鍦板潃涓庣綉缁滃悗閲嶈瘯', 'danger');
        } else {
          showToast('璇锋眰寮傚父: ' + err, 'danger');
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
  if (!confirm(`纭畾瑕佹案涔呭垹闄?ID 涓?#${logId} 鐨勬帹閫佹棩蹇楀悧锛焋)) return;

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
      alert('鍒犻櫎澶辫触: ' + (data.message || '绯荤粺閿欒'));
    }
  })
  .catch(err => alert('缃戠粶寮傚父: ' + err));
}

function submitBatchDeleteLogs() {
  const checked = Array.from(document.querySelectorAll('.log-item-checkbox:checked'));
  if (checked.length === 0) {
    alert('璇峰厛鍕鹃€夐渶瑕佸垹闄ょ殑鎺ㄩ€佹棩蹇楋紒');
    return;
  }
  const ids = checked.map(cb => parseInt(cb.value, 10));
  if (!confirm(`纭畾瑕佹壒閲忓垹闄ゅ凡閫変腑鐨?${ids.length} 鏉℃帹閫佹棩蹇楀悧锛熷垹闄ゅ悗涓嶅彲鎭㈠锛乣)) return;

  const batchBtn = document.getElementById('btnBatchDeleteLogs');
  const origHtml = batchBtn.innerHTML;
  batchBtn.disabled = true;
  batchBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>鍒犻櫎涓?..';

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
      alert('鎵归噺鍒犻櫎澶辫触: ' + (data.message || '绯荤粺閿欒'));
    }
  })
  .catch(err => {
    batchBtn.disabled = false;
    batchBtn.innerHTML = origHtml;
    alert('缃戠粶寮傚父: ' + err);
  });
}

function submitClearAllLogs() {
  if (!confirm('璀﹀憡锛氭竻绌哄叏閮ㄦ棩蹇楀皢褰诲簳鍒犻櫎鍘嗗彶鎵€鏈?Webhook 鎺ㄩ€佸強浜や粯璁板綍锛屼笉鍙仮澶嶏紒\n\n纭畾瑕佹竻绌哄叏閮ㄦ棩蹇楀悧锛?)) return;

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
      alert('娓呯┖澶辫触: ' + (data.message || '绯荤粺閿欒'));
    }
  })
  .catch(err => alert('缃戠粶寮傚父: ' + err));
}

// V8: 閫氱敤 toast 鎻愮ず瀹瑰櫒 + 鍑芥暟锛堝叏灞€鍙敤锛屾浛鎹㈠師鐢?alert 鎻愬崌鍙嶉浣撻獙锛?
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


