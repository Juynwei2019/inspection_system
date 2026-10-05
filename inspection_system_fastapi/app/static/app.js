/* 巡檢系統：同源 FastAPI API 版。展示資料由伺服器 SQLite 提供。 */
(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);
  const state = {
    page: 'home', db: {locations: [], items: [], links: {}}, drafts: [], current: null,
    selected: null, resultPage: 1, resultResponse: null, dashboard: null,
    dirty: false, saving: null, timer: null, noticeTimer: null, navigation: 0, user: null,
    users: [], editingUserId: null, resettingUserId: null,
    casePage: 1, cases: [], currentCase: null, assignees: [],
    schedules: [], tasks: [], scheduleAssignees: [], editingScheduleId: null,
  };

  async function api(path, options = {}) {
    const headers = {...(options.headers || {})};
    if (!(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
    const response = await fetch(`/api/v1${path}`, {
      ...options,
      credentials: 'same-origin',
      headers,
    });
    let body;
    try { body = await response.json(); } catch { body = {}; }
    if (response.status === 401) {
      location.replace('/login');
      throw new Error('登入狀態已失效，請重新登入');
    }
    if (!response.ok) {
      const detail = body.detail;
      const message = typeof detail === 'object' && !Array.isArray(detail)
        ? detail.message : response.status === 422 ? '輸入資料有誤，請檢查欄位' : `伺服器回應 ${response.status}`;
      const error = new Error(message || '請求失敗');
      error.status = response.status;
      error.code = detail?.code;
      throw error;
    }
    return body;
  }

  function flash(message) {
    const el = $('#notice');
    el.textContent = message;
    el.classList.remove('hidden');
    clearTimeout(state.noticeTimer);
    state.noticeTimer = setTimeout(() => el.classList.add('hidden'), 4200);
  }
  function report(error) { flash(error?.message || '操作失敗，請稍後再試'); }
  const post = (path, data) => api(path, {method: 'POST', body: JSON.stringify(data)});
  const patch = (path, data) => api(path, {method: 'PATCH', body: JSON.stringify(data)});
  const put = (path, data) => api(path, {method: 'PUT', body: JSON.stringify(data)});
  const remove = path => api(path, {method: 'DELETE'});
  const links = id => state.db.links[id] || [];
  const activeItems = id => links(id).filter(m => state.db.items.some(i => i.id === m.itemId && i.active));
  const dateText = value => value ? new Date(value).toLocaleString('zh-TW', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false
  }) : '—';
  const localDateValue = value => {
    const date = value || new Date();
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  };
  const adaptLocation = x => ({...x, active: x.is_active});
  const adaptItem = x => ({...x, active: x.is_active,
    type: x.result_type === 'normal_abnormal' ? '正常／異常' : '正常／異常／不適用'});
  const adaptRecord = x => ({...x, locationId: x.location_id, locationCode: x.location_code,
    locationName: x.location_name, startedAt: x.started_at, submittedAt: x.submitted_at,
    results: (x.results || []).map(r => ({...r, itemId: r.item_id,
      type: r.result_type === 'normal_abnormal' ? '正常／異常' : '正常／異常／不適用',
      required: r.is_required, order: r.sort_order,
      attachments: r.attachments || [],
      result: ({normal: '正常', abnormal: '異常', na: '不適用'})[r.result] || null}))});
  const toResult = value => ({'正常': 'normal', '異常': 'abnormal', '不適用': 'na'})[value] || null;

  async function loadCurrentUser() {
    const data = await api('/auth/me');
    state.user = data.user;
    $('#account-name').textContent = data.user.display_name;
    $('#account-meta').textContent = `${data.user.username} ・ ${data.user.role_label}`;
    const canMaintain = ['system_admin', 'inspection_manager'].includes(data.user.role);
    const canInspect = ['system_admin', 'inspection_manager', 'inspector'].includes(data.user.role);
    document.querySelectorAll('[data-system-admin-only]').forEach(element =>
      element.classList.toggle('hidden', data.user.role !== 'system_admin'));
    document.querySelectorAll('[data-maintenance-only]').forEach(element =>
      element.classList.toggle('hidden', !canMaintain));
    document.querySelectorAll('[data-inspection-only]').forEach(element =>
      element.classList.toggle('hidden', !canInspect));
    if (data.user.must_change_password) {
      $('#password-dialog .modal-head h2').textContent = '首次登入，請修改密碼';
      $('#password-dialog .modal-head p').textContent = '完成密碼修改後才能使用巡檢系統。';
      $('#close-password').classList.add('hidden');
      $('#cancel-password').classList.add('hidden');
      $('#password-dialog').showModal();
      $('#current-password').focus();
    }
  }

  async function loadBootstrap() {
    const data = await api('/bootstrap');
    state.db = {
      locations: data.locations.map(adaptLocation), items: data.items.map(adaptItem),
      links: Object.fromEntries(Object.entries(data.links).map(([id, list]) => [id, list.map(m => ({
        itemId: m.item_id, required: m.is_required, order: m.sort_order
      }))])),
    };
    if (!state.db.locations.some(x => x.id === state.selected)) state.selected = state.db.locations[0]?.id || null;
  }
  async function loadDrafts() {
    const response = await api('/inspections?status=draft&page_size=100');
    state.drafts = response.items.map(adaptRecord);
  }

  function showPage(page) {
    state.page = page;
    const maintenance = ['locations', 'items', 'mapping'].includes(page);
    const config = {
      home: ['主頁', '工作總覽', '巡檢工作總覽', '從這裡開始巡檢、維護地點與項目，或查看已提交的結果。', ''],
      locations: ['維護模組', '巡檢地點', '巡檢地點維護', '建立與管理需要巡檢的廠區、樓層及區域。', '＋ 新增地點'],
      items: ['維護模組', '巡檢項目', '巡檢項目維護', '設定巡檢內容與檢查標準，供不同地點重複使用。', '＋ 新增項目'],
      mapping: ['維護模組', '地點項目設定', '地點項目設定', '指定每個地點需要檢查的項目及必填規則。', '＋ 新增項目'],
      schedule: ['巡檢排程', '任務與排程', '巡檢排程', '查看待辦、逾期任務，並設定週期性巡檢。', '＋ 新增排程'],
      inspection: ['巡檢模組', '開始巡檢', '開始巡檢', '選擇巡檢地點，逐項填寫並提交結果。', ''],
      results: ['結果查詢', '巡檢結果查詢', '巡檢結果查詢', '依地點、時間與檢查結果查找已提交的巡檢紀錄。', ''],
      abnormal: ['異常追蹤', '異常案件', '異常改善追蹤', '指派負責人、追蹤期限，完成改善、複查與結案。', ''],
      users: ['帳號管理', '使用者與權限', '帳號與角色權限', '建立帳號、分配角色、重設密碼並追蹤重要操作。', '＋ 新增帳號'],
    }[page];
    const [module, crumb, title, description, action] = config;
    $('#module-crumb').textContent = module;
    $('#crumb').textContent = crumb;
    $('#page-eyebrow').textContent = page === 'home' ? 'OVERVIEW' : maintenance ? 'MASTER DATA' : ['inspection', 'schedule'].includes(page) ? 'INSPECTION' : page === 'users' ? 'ACCESS CONTROL' : 'REPORTS';
    $('#page-title').textContent = title;
    $('#page-description').textContent = description;
    const allowedAction = action && (page !== 'schedule' || ['system_admin', 'inspection_manager'].includes(state.user?.role));
    $('#create-button').textContent = action;
    $('#create-button').classList.toggle('hidden', !allowedAction);
    $('#maintenance-metrics').classList.toggle('hidden', !maintenance);
    $('#maintenance-subnav').classList.toggle('hidden', !maintenance);
    document.querySelectorAll('nav[aria-label="主功能模組"] button').forEach(b => b.classList.toggle('active',
      maintenance ? b.dataset.mainMaintenance === 'true' : b.dataset.page === page));
    document.querySelectorAll('#maintenance-subnav button').forEach(b => b.classList.toggle('active', b.dataset.page === page));
    ['home', 'locations', 'items', 'mapping', 'schedule', 'inspection', 'results', 'abnormal', 'users'].forEach(key =>
      $(`#${key}-page`).classList.toggle('hidden', key !== page));
  }

  async function setPage(page) {
    if (['locations', 'items', 'mapping'].includes(page) && !['system_admin', 'inspection_manager'].includes(state.user?.role)) {
      flash('你沒有權限使用維護模組');
      page = 'home';
    }
    if (['inspection', 'schedule'].includes(page) && !['system_admin', 'inspection_manager', 'inspector'].includes(state.user?.role)) {
      flash('你的角色不具備巡檢權限'); page = 'home';
    }
    if (page === 'users' && state.user?.role !== 'system_admin') {
      flash('帳號管理僅限系統管理員'); page = 'home';
    }
    if (state.current && state.dirty && page !== 'inspection') {
      try { await persistDraft(); } catch (error) { report(error); return; }
    }
    const navigation = ++state.navigation;
    showPage(page);
    try {
      if (['locations', 'items', 'mapping', 'inspection', 'schedule'].includes(page)) await loadBootstrap();
      if (page === 'inspection') await loadDrafts();
      if (navigation !== state.navigation) return;
      if (page === 'home') await renderHome();
      if (page === 'locations' || page === 'items' || page === 'mapping') renderMaintenance();
      if (page === 'inspection') {
        if (state.current) { renderInspectionForm(state.current); showInspectionStep('work'); }
        else { showInspectionStep('pick'); renderInspectionLocations(); }
      }
      if (page === 'schedule') await renderSchedules();
      if (page === 'results') await renderResults();
      if (page === 'abnormal') await renderCases();
      if (page === 'users') await renderUsers();
    } catch (error) { report(error); }
  }

  function renderMaintenance() {
    $('#metric-locations').textContent = state.db.locations.filter(x => x.active).length;
    $('#metric-items').textContent = state.db.items.filter(x => x.active).length;
    $('#metric-links').textContent = Object.values(state.db.links).reduce((count, list) => count + list.length, 0);
    if (state.page === 'locations') renderLocations();
    if (state.page === 'items') renderItems();
    if (state.page === 'mapping') renderMapping();
  }

  async function renderHome() {
    const canInspect = ['system_admin', 'inspection_manager', 'inspector'].includes(state.user?.role);
    const today = localDateValue();
    const [data, tasks] = await Promise.all([api('/dashboard'), canInspect
      ? api(`/inspection-tasks?date_from=${today}&date_to=${today}&page_size=100`)
      : Promise.resolve(null)]);
    if (state.page !== 'home') return;
    state.dashboard = data;
    $('#home-location-count').textContent = data.available_locations;
    $('#home-draft-count').textContent = data.draft_count;
    $('#home-submitted-count').textContent = data.submitted_count;
    $('#home-abnormal-count').textContent = data.abnormal_count;
    if (tasks) {
      $('#home-task-count').textContent = tasks.total;
      $('#home-task-overdue').textContent = tasks.summary.overdue;
    }
    $('#home-drafts').innerHTML = data.drafts.map(r => `<div class="home-list-row"><div><strong>${esc(r.location_name)}</strong><small>已填 ${r.answered_count}／${r.item_count} 項 ・ ${esc(r.inspector || '尚未填寫巡檢人員')}</small></div><button class="quiet" data-resume-id="${esc(r.id)}">繼續 →</button></div>`).join('') || '<p class="home-list-empty">目前沒有待續草稿，可以開始新的巡檢。</p>';
    $('#home-recent').innerHTML = data.recent.map(r => `<div class="home-list-row"><div><strong>${esc(r.location_name)}</strong><small>${esc(dateText(r.submitted_at))} ・ ${r.abnormal_count ? '有異常' : '無異常'}</small></div><button class="quiet" data-result-detail="${esc(r.id)}">查看 →</button></div>`).join('') || '<p class="home-list-empty">尚無已提交的巡檢紀錄。</p>';
  }

  function renderLocations() {
    const q = $('#location-search').value.trim().toLocaleLowerCase(), filter = $('#location-filter').value;
    const rows = state.db.locations.filter(x => (filter === 'all' || x.active === (filter === 'active')) &&
      [x.code, x.name, x.area].some(value => value.toLocaleLowerCase().includes(q)));
    $('#locations-body').innerHTML = rows.map(x => `<tr><td class="title-cell"><strong>${esc(x.name)}</strong><div class="sub">${esc(x.description || '—')}</div></td><td class="code">${esc(x.code)}</td><td>${esc(x.area || '—')}</td><td>${links(x.id).length} 項</td><td><span class="pill ${x.active ? '' : 'off'}">${x.active ? '啟用' : '停用'}</span></td><td><div class="actions"><button class="quiet" data-action="map" data-id="${esc(x.id)}">設定項目</button><button class="quiet" data-action="edit-location" data-id="${esc(x.id)}">編輯</button><button class="quiet" data-action="toggle-location" data-id="${esc(x.id)}">${x.active ? '停用' : '啟用'}</button></div></td></tr>`).join('') || '<tr><td colspan="6" class="empty">沒有符合條件的地點。可調整搜尋條件或新增地點。</td></tr>';
  }
  function renderItems() {
    const q = $('#item-search').value.trim().toLocaleLowerCase(), filter = $('#item-filter').value;
    const rows = state.db.items.filter(x => (filter === 'all' || x.active === (filter === 'active')) &&
      [x.code, x.name, x.category].some(value => value.toLocaleLowerCase().includes(q)));
    $('#items-body').innerHTML = rows.map(x => `<tr><td class="title-cell"><strong>${esc(x.name)}</strong><div class="sub">${esc(x.description || '—')}</div></td><td class="code">${esc(x.code)}</td><td>${esc(x.category || '—')}</td><td>${esc(x.type)}</td><td>${state.db.locations.filter(l => links(l.id).some(m => m.itemId === x.id)).length} 處</td><td><span class="pill ${x.active ? '' : 'off'}">${x.active ? '啟用' : '停用'}</span></td><td><div class="actions"><button class="quiet" data-action="edit-item" data-id="${esc(x.id)}">編輯</button><button class="quiet" data-action="toggle-item" data-id="${esc(x.id)}">${x.active ? '停用' : '啟用'}</button></div></td></tr>`).join('') || '<tr><td colspan="7" class="empty">沒有符合條件的項目。可調整搜尋條件或新增項目。</td></tr>';
  }
  function renderMapping() {
    const id = state.selected;
    $('#mapping-locations').innerHTML = '<h3>選擇地點</h3>' + state.db.locations.map(x => `<button class="${x.id === id ? 'active' : ''}" data-select-location="${esc(x.id)}">${esc(x.name)}<small>${esc(x.code)} ・ ${links(x.id).length} 項${x.active ? '' : ' ・ 已停用'}</small></button>`).join('');
    const location = state.db.locations.find(x => x.id === id);
    $('#mapping-title').textContent = location?.name || '尚無巡檢地點';
    $('#mapping-subtitle').textContent = location ? `${location.code}　·　${location.area || '未設定區域'}` : '請先建立巡檢地點';
    const q = $('#mapping-search').value.trim().toLocaleLowerCase(), filter = $('#mapping-filter').value;
    const rows = state.db.items.filter(x => [x.code, x.name, x.category].some(y => y.toLocaleLowerCase().includes(q)) &&
      (filter === 'all' || links(id).some(m => m.itemId === x.id))).sort((a, b) =>
      (links(id).find(m => m.itemId === a.id)?.order ?? Infinity) - (links(id).find(m => m.itemId === b.id)?.order ?? Infinity));
    $('#mapping-rows').innerHTML = location ? rows.map(x => {
      const mapping = links(id).find(m => m.itemId === x.id);
      return `<div class="map-row"><label><input type="checkbox" data-map-select="${esc(x.id)}" ${mapping ? 'checked' : ''}><span><strong>${esc(x.name)}</strong><span class="sub" style="display:block">${esc(x.code)} ・ ${esc(x.category || '未分類')}${x.active ? '' : ' ・ 已停用'}</span></span></label><label class="required"><input type="checkbox" data-map-required="${esc(x.id)}" ${mapping?.required ? 'checked' : ''} ${mapping ? '' : 'disabled'}>必填</label><select data-map-order="${esc(x.id)}" aria-label="${esc(x.name)}的顯示順序" ${mapping ? '' : 'disabled'}>${Array.from({length: Math.max(links(id).length, 1)}, (_, i) => `<option value="${i + 1}" ${mapping?.order === i + 1 ? 'selected' : ''}>第 ${i + 1} 項</option>`).join('')}</select><div class="mini">${mapping ? '已加入' : '未加入'}</div></div>`;
    }).join('') || '<div class="empty">沒有符合條件的項目。</div>' : '<div class="empty">請先新增巡檢地點。</div>';
    $('#mapping-footer').textContent = location ? `已設定 ${links(id).length} 個項目。設定成功後會儲存到伺服器。` : '新增地點後即可設定項目。';
  }

  function field(name, label, value, required = false, kind = 'text', extra = '') {
    return `<div class="field"><label for="field-${name}">${label}${required ? ' <b>*</b>' : ''}</label>${kind === 'textarea'
      ? `<textarea id="field-${name}" name="${name}" ${required ? 'required' : ''} maxlength="300">${esc(value)}</textarea>`
      : `<input id="field-${name}" name="${name}" type="text" value="${esc(value)}" ${required ? 'required' : ''} maxlength="80" ${extra}>`}</div>`;
  }
  let editorMode = null, editingId = null;
  function openEditor(mode, id = null) {
    editorMode = mode; editingId = id;
    const isLocation = mode === 'location';
    const value = (isLocation ? state.db.locations : state.db.items).find(x => x.id === id) || {};
    $('#editor-title').textContent = (id ? '編輯' : '新增') + (isLocation ? '巡檢地點' : '巡檢項目');
    $('#editor-subtitle').textContent = isLocation ? '建立巡檢位置並設定所屬區域。' : '定義各地點可共用的檢查項目。';
    $('#form-fields').innerHTML = isLocation
      ? `<div class="grid2">${field('code', '地點代碼', value.code || '', true, 'text', 'pattern="[A-Za-z0-9_-]+"')}${field('area', '所屬區域', value.area || '')}</div>${field('name', '地點名稱', value.name || '', true)}${field('description', '備註說明', value.description || '', false, 'textarea')}<div class="field"><label for="field-active">使用狀態</label><select name="active" id="field-active"><option value="true" ${value.active !== false ? 'selected' : ''}>啟用</option><option value="false" ${value.active === false ? 'selected' : ''}>停用</option></select></div>`
      : `<div class="grid2">${field('code', '項目代碼', value.code || '', true, 'text', 'pattern="[A-Za-z0-9_-]+"')}${field('category', '項目分類', value.category || '')}</div>${field('name', '巡檢項目名稱', value.name || '', true)}${field('description', '檢查標準／說明', value.description || '', false, 'textarea')}<div class="grid2"><div class="field"><label for="field-type">檢查方式 <b>*</b></label><select name="type" id="field-type"><option value="正常／異常／不適用">正常／異常／不適用</option><option value="正常／異常">正常／異常</option></select></div><div class="field"><label for="field-active">使用狀態</label><select name="active" id="field-active"><option value="true" ${value.active !== false ? 'selected' : ''}>啟用</option><option value="false" ${value.active === false ? 'selected' : ''}>停用</option></select></div></div>`;
    if (!isLocation) $('#field-type').value = value.type || '正常／異常／不適用';
    $('#editor').showModal(); $('#field-code').focus();
  }
  async function saveEditor(event) {
    event.preventDefault();
    const data = new FormData(event.currentTarget), isLocation = editorMode === 'location';
    const value = {code: String(data.get('code')).trim().toUpperCase(), name: String(data.get('name')).trim(),
      description: String(data.get('description') || '').trim(), is_active: data.get('active') === 'true'};
    if (!value.code || !value.name) { flash('代碼與名稱不可空白'); return; }
    if (isLocation) value.area = String(data.get('area') || '').trim();
    else {
      value.category = String(data.get('category') || '').trim();
      value.result_type = data.get('type') === '正常／異常' ? 'normal_abnormal' : 'normal_abnormal_na';
    }
    const endpoint = isLocation ? '/locations' : '/items';
    try {
      const saved = editingId ? await patch(`${endpoint}/${encodeURIComponent(editingId)}`, value) : await post(endpoint, value);
      await loadBootstrap();
      if (!editingId && isLocation) state.selected = saved.id;
      $('#editor').close(); renderMaintenance(); flash((isLocation ? '地點' : '項目') + '已儲存');
    } catch (error) { report(error); }
  }

  let mappingBusy = false;
  async function updateMapping(target) {
    if (mappingBusy || !state.selected) return;
    const itemId = target.dataset.mapSelect || target.dataset.mapRequired || target.dataset.mapOrder;
    if (!itemId) return;
    mappingBusy = true;
    $('#mapping-rows').style.pointerEvents = 'none';
    const list = links(state.selected).map(x => ({...x}));
    const existing = list.find(x => x.itemId === itemId);
    if (target.dataset.mapSelect) {
      if (target.checked && !existing) list.push({itemId, required: true, order: list.length + 1});
      if (!target.checked && existing) list.splice(list.indexOf(existing), 1);
    } else if (existing && target.dataset.mapRequired) existing.required = target.checked;
    else if (existing && target.dataset.mapOrder) {
      list.sort((a, b) => a.order - b.order);
      list.splice(list.indexOf(existing), 1);
      list.splice(Number(target.value) - 1, 0, existing);
      list.forEach((x, i) => x.order = i + 1);
    }
    list.sort((a, b) => a.order - b.order).forEach((x, i) => x.order = i + 1);
    try {
      await put(`/locations/${encodeURIComponent(state.selected)}/items`, {items: list.map(x => ({
        item_id: x.itemId, sort_order: x.order, is_required: x.required
      }))});
      await loadBootstrap(); renderMaintenance(); flash('地點項目設定已儲存');
    } catch (error) { await loadBootstrap(); renderMaintenance(); report(error); }
    finally { mappingBusy = false; $('#mapping-rows').style.pointerEvents = ''; }
  }

  function showInspectionStep(step) {
    ['pick', 'work', 'success'].forEach(name => $('#inspection-' + name).classList.toggle('hidden', name !== step));
  }
  function renderInspectionLocations() {
    const q = $('#inspection-search').value.trim().toLocaleLowerCase();
    const available = state.db.locations.filter(location => location.active ||
      state.drafts.some(r => r.locationId === location.id)).filter(location =>
      [location.code, location.name, location.area].some(value => value.toLocaleLowerCase().includes(q)));
    $('#inspection-locations').innerHTML = available.map(location => {
      const draft = state.drafts.find(r => r.locationId === location.id);
      const count = activeItems(location.id).length;
      const canStart = !!draft || (location.active && count > 0);
      return `<article class="location-card"><div><span class="code">${esc(location.code)} ・ ${esc(location.area || '未設定區域')}</span><h3>${esc(location.name)}</h3></div><p>${draft ? '已有未完成的巡檢草稿' : location.active ? count ? '依維護設定進行逐項檢查' : '尚未設定啟用的巡檢項目' : '此地點已停用，但既有草稿可以繼續'}</p><div class="card-foot"><small>${draft ? `${draft.results.filter(x => x.result).length}／${draft.results.length} 已填寫` : `${count} 個檢查項目`}</small><button class="${canStart ? 'primary' : 'secondary'}" data-inspect-location="${esc(location.id)}" ${canStart ? '' : 'disabled'}>${draft ? '繼續巡檢 →' : canStart ? '開始巡檢 →' : '暫不可巡檢'}</button></div></article>`;
    }).join('') || '<div class="panel empty" style="grid-column:1/-1">沒有可巡檢的地點。請先在維護模組設定地點與項目。</div>';
  }
  async function startInspection(locationId) {
    try {
      if (state.current && state.dirty) await persistDraft();
      if (state.page !== 'inspection') await setPage('inspection');
      let record = state.drafts.find(r => r.locationId === locationId);
      if (!record) record = adaptRecord(await post('/inspections', {location_id: locationId}));
      state.current = record;
      state.dirty = false;
      showInspectionStep('work'); renderInspectionForm(record);
      window.scrollTo({top: 0, behavior: 'smooth'});
    } catch (error) { report(error); }
  }
  async function resumeDraft(id) {
    try {
      await setPage('inspection');
      const record = adaptRecord(await api(`/inspections/${encodeURIComponent(id)}`));
      if (record.status !== 'draft') { flash('此巡檢已提交'); await setPage('results'); return; }
      state.current = record; state.dirty = false;
      renderInspectionForm(record); showInspectionStep('work');
    } catch (error) { report(error); }
  }
  function renderInspectionForm(record) {
    $('#inspection-location-title').textContent = record.locationName;
    $('#inspection-location-meta').textContent = `${record.locationCode}　・　${record.area || '未設定區域'}　・　開始時間 ${dateText(record.startedAt)}`;
    $('#inspector-name').value = record.inspector || state.user?.display_name || '';
    $('#inspection-item-list').innerHTML = record.results.map((r, i) =>
      `<article class="inspection-item" data-inspection-row="${esc(r.itemId)}"><div class="item-top"><div><div class="item-no">項目 ${String(i + 1).padStart(2, '0')} ・ ${esc(r.category || '一般檢查')}</div><h3>${esc(r.name)}</h3><p>${esc(r.description || '依現場狀況檢查')}</p></div><span class="${r.required ? 'badge-required' : 'badge-optional'}">${r.required ? '必填' : '選填'}</span></div><div class="choice-row">${(r.type === '正常／異常' ? ['正常', '異常'] : ['正常', '異常', '不適用']).map(v => `<label><input type="radio" name="result-${esc(r.itemId)}" data-inspect-result="${esc(r.itemId)}" value="${v}" ${r.result === v ? 'checked' : ''}><span>${v}</span></label>`).join('')}</div><textarea data-inspect-note="${esc(r.itemId)}" maxlength="500" aria-label="${esc(r.name)}的備註" placeholder="${r.result === '異常' ? '請說明異常情形（必填）' : '備註或補充說明（選填）'}">${esc(r.note || '')}</textarea><div class="photo-section"><div class="photo-head"><strong>現場照片</strong><small>${r.attachments.length}／5 張・單張上限 5 MB</small></div><div class="photo-grid">${r.attachments.map(photo => `<figure class="photo-thumb"><a href="${esc(photo.content_url)}" target="_blank" rel="noopener"><img src="${esc(photo.content_url)}" alt="${esc(photo.original_name)}" loading="lazy"></a><button type="button" data-photo-delete="${esc(photo.id)}" data-item-id="${esc(r.itemId)}" aria-label="刪除 ${esc(photo.original_name)}">×</button></figure>`).join('')}<label class="photo-add ${r.attachments.length >= 5 ? 'hidden' : ''}"><input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" data-photo-input="${esc(r.itemId)}"><span>＋</span><small>拍照／選取</small></label></div></div></article>`).join('');
    updateProgress(record);
    $('#inspection-save-status').textContent = state.dirty ? '尚未儲存到伺服器' : '已由伺服器儲存';
  }
  async function uploadPhoto(itemId, input) {
    const record = state.current;
    const result = record?.results.find(x => x.itemId === itemId);
    const file = input.files?.[0];
    if (!record || !result || !file) return;
    if (file.size > 5 * 1024 * 1024) { input.value = ''; flash('單張照片不可超過 5 MB'); return; }
    input.disabled = true;
    const data = new FormData(); data.append('photo', file, file.name);
    try {
      const photo = await api(`/inspections/${encodeURIComponent(record.id)}/results/${encodeURIComponent(itemId)}/attachments`, {method: 'POST', body: data});
      result.attachments.push(photo); renderInspectionForm(record); flash('照片已上傳');
    } catch (error) { report(error); input.disabled = false; input.value = ''; }
  }
  async function deletePhoto(photoId, itemId) {
    const result = state.current?.results.find(x => x.itemId === itemId);
    if (!result || !confirm('確定刪除這張照片嗎？')) return;
    try {
      await remove(`/attachments/${encodeURIComponent(photoId)}`);
      result.attachments = result.attachments.filter(x => x.id !== photoId);
      renderInspectionForm(state.current); flash('照片已刪除');
    } catch (error) { report(error); }
  }
  function updateProgress(record) {
    const answered = record.results.filter(x => x.result).length;
    $('#inspection-progress-label').textContent = `已填寫 ${answered}／${record.results.length} 項`;
    $('#inspection-progress-fill').style.width = `${record.results.length ? Math.round(answered / record.results.length * 100) : 0}%`;
  }
  function markDirty() {
    state.dirty = true;
    $('#inspection-save-status').textContent = '等待儲存到伺服器…';
    clearTimeout(state.timer);
    state.timer = setTimeout(() => { persistDraft().catch(report); }, 650);
  }
  async function persistDraft() {
    clearTimeout(state.timer);
    if (!state.current) return;
    if (state.saving) {
      await state.saving;
      if (state.dirty) return persistDraft();
      return;
    }
    if (!state.dirty) return;
    const record = state.current;
    const task = (async () => {
      while (state.current === record && state.dirty) {
        state.dirty = false;
        const payload = {version: record.version, inspector: record.inspector || '',
          results: record.results.map(r => ({item_id: r.itemId, result: toResult(r.result), note: r.note || ''}))};
        $('#inspection-save-status').textContent = '正在儲存…';
        try {
          const updated = await patch(`/inspections/${encodeURIComponent(record.id)}/draft`, payload);
          record.version = updated.version;
        } catch (error) {
          state.dirty = true;
          $('#inspection-save-status').textContent = '儲存失敗，請重試';
          throw error;
        }
      }
      $('#inspection-save-status').textContent = '草稿已儲存於伺服器';
    })();
    state.saving = task;
    try { await task; } finally { if (state.saving === task) state.saving = null; }
  }
  async function leaveInspection() {
    try {
      await persistDraft();
      state.current = null;
      await loadDrafts();
      showInspectionStep('pick'); renderInspectionLocations();
    } catch (error) { report(error); }
  }
  async function reviewInspection() {
    const record = state.current;
    if (!record) return;
    record.inspector = $('#inspector-name').value.trim();
    if (!record.inspector) { flash('請填寫巡檢人員'); $('#inspector-name').focus(); return; }
    state.dirty = true;
    try { await persistDraft(); } catch (error) { report(error); return; }
    const missing = record.results.find(x => x.required && !x.result);
    const abnormal = record.results.find(x => x.result === '異常' && !x.note.trim());
    if (missing || abnormal) {
      const row = $(`[data-inspection-row="${CSS.escape((missing || abnormal).itemId)}"]`);
      row?.classList.add('alert'); row?.scrollIntoView({behavior: 'smooth', block: 'center'});
      flash(missing ? '請完成所有必填項目' : '異常項目請填寫說明');
      setTimeout(() => row?.classList.remove('alert'), 3200);
      return;
    }
    const count = v => record.results.filter(x => x.result === v).length;
    $('#inspection-summary').innerHTML = `<div><strong>巡檢地點：</strong>${esc(record.locationName)}</div><div><strong>巡檢人員：</strong>${esc(record.inspector)}</div><div><strong>已填項目：</strong>${record.results.filter(x => x.result).length}／${record.results.length}</div><div><strong>結果統計：</strong>正常 ${count('正常')} 項、異常 ${count('異常')} 項、不適用 ${count('不適用')} 項</div>${record.results.some(x => !x.result) ? `<div class="summary-warn">另有 ${record.results.filter(x => !x.result).length} 個選填項目未檢查，將以「未檢查」保存。</div>` : ''}${count('異常') ? '<div class="summary-warn">請確認異常項目與說明後再提交。</div>' : ''}`;
    $('#inspection-confirm').showModal();
  }
  async function submitInspection() {
    const record = state.current;
    if (!record) return;
    const button = $('#inspection-confirm-submit'); button.disabled = true;
    try {
      await persistDraft();
      const submitted = adaptRecord(await post(`/inspections/${encodeURIComponent(record.id)}/submit`, {version: record.version}));
      $('#inspection-confirm').close();
      state.current = null; state.dirty = false;
      $('#inspection-success-detail').textContent = `巡檢編號 ${submitted.number}　・　${submitted.locationName}　・　${submitted.results.length} 個項目。可在巡檢結果查詢中查看明細。`;
      showInspectionStep('success'); window.scrollTo({top: 0, behavior: 'smooth'});
    } catch (error) { $('#inspection-confirm').close(); report(error); }
    finally { button.disabled = false; }
  }

  function renderResultLocations() {
    const select = $('#result-location'), old = select.value;
    select.innerHTML = '<option value="">全部地點</option>' + state.db.locations.map(location =>
      `<option value="${esc(location.id)}">${esc(location.name)}</option>`).join('');
    select.value = state.db.locations.some(x => x.id === old) ? old : '';
  }
  let resultRequest = 0;
  async function renderResults() {
    const requestId = ++resultRequest;
    if (!state.db.locations.length) await loadBootstrap();
    if (requestId !== resultRequest || state.page !== 'results') return;
    renderResultLocations();
    const params = new URLSearchParams({status: 'submitted', page: String(state.resultPage), page_size: '10'});
    const input = {query: '#result-search', date_from: '#result-date-from', date_to: '#result-date-to', location_id: '#result-location'};
    for (const [key, selector] of Object.entries(input)) if ($(selector).value.trim()) params.set(key, $(selector).value.trim());
    if ($('#result-status').value) params.set('has_abnormal', String($('#result-status').value === 'abnormal'));
    const response = await api(`/inspections?${params}`);
    if (requestId !== resultRequest || state.page !== 'results') return;
    state.resultResponse = response;
    const items = response.items.map(adaptRecord), pages = Math.max(1, Math.ceil(response.total / 10));
    if (state.resultPage > pages) { state.resultPage = pages; return renderResults(); }
    $('#result-count').textContent = response.total;
    $('#result-normal-count').textContent = response.normal_count;
    $('#result-abnormal-count').textContent = response.abnormal_count;
    const start = (state.resultPage - 1) * 10;
    $('#result-range').textContent = response.total ? `顯示 ${start + 1}–${start + items.length} 筆，共 ${response.total} 筆` : '目前沒有符合條件的紀錄';
    $('#result-body').innerHTML = items.map(r => {
      const bad = r.results.filter(x => x.result === '異常').length;
      const untested = r.results.filter(x => !x.result).length;
      return `<tr><td class="code">${esc(r.number || r.id)}</td><td class="title-cell"><strong>${esc(r.locationName)}</strong><div class="sub">${esc(r.locationCode || '')} ・ ${esc(r.area || '未設定區域')}</div></td><td>${esc(r.inspector || '—')}</td><td>${esc(dateText(r.submittedAt))}</td><td><span class="pill ${bad ? 'problem' : ''}">${bad ? `異常 ${bad} 項` : '無異常'}</span></td><td>${r.results.length} 項${untested ? `<div class="sub">${untested} 項未檢查</div>` : ''}</td><td style="text-align:right"><button class="quiet" data-result-detail="${esc(r.id)}">查看明細 →</button></td></tr>`;
    }).join('') || `<tr><td colspan="7" class="empty">${response.total ? '此頁沒有紀錄。' : '沒有符合條件的巡檢紀錄；若尚未巡檢，請先提交一筆結果。'}</td></tr>`;
    $('#result-page-label').textContent = `第 ${state.resultPage}／${pages} 頁`;
    $('#result-prev').disabled = state.resultPage <= 1;
    $('#result-next').disabled = state.resultPage >= pages;
  }
  async function openResultDetail(id, focusResultId = null) {
    try {
      const r = adaptRecord(await api(`/inspections/${encodeURIComponent(id)}`));
      if (r.status !== 'submitted') { flash('草稿尚未提交，無法查詢結果'); return; }
      $('#detail-number').textContent = r.number || r.id;
      $('#detail-headline').innerHTML = `<div>巡檢地點<strong>${esc(r.locationName)}（${esc(r.locationCode || '—')}）</strong></div><div>巡檢人員<strong>${esc(r.inspector || '—')}</strong></div><div>開始時間<strong>${esc(dateText(r.startedAt))}</strong></div><div>提交時間<strong>${esc(dateText(r.submittedAt))}</strong></div><div>整體結果<strong>${r.results.some(x => x.result === '異常') ? `有異常・${r.results.filter(x => x.result === '異常').length} 項` : '無異常'}</strong></div><div>檢查項目<strong>${r.results.length} 項</strong></div>`;
      $('#detail-list').innerHTML = '<h3>逐項巡檢結果</h3>' + [...r.results].sort((a, b) => a.order - b.order).map((item, i) => {
        const value = item.result || '未檢查', badge = value === '異常' ? 'bad' : value === '正常' ? '' : 'muted';
        const caseLink = item.abnormal_case ? `<div class="case-link"><span>異常案件 ${esc(item.abnormal_case.case_number)}・${esc(caseStatusLabels[item.abnormal_case.status] || item.abnormal_case.status)}</span><button class="quiet" data-linked-case="${esc(item.abnormal_case.id)}">查看改善追蹤 →</button></div>` : '';
        return `<div class="detail-card" data-result-card="${esc(item.id)}"><div class="detail-card-top"><div><div class="item-no">項目 ${String(i + 1).padStart(2, '0')} ・ ${esc(item.category || '一般檢查')} ・ ${esc(item.code || '')}</div><strong>${esc(item.name)}</strong></div><span class="detail-badge ${badge}">${esc(value)}</span></div>${item.description ? `<p>${esc(item.description)}</p>` : ''}${item.note ? `<div class="note">${esc(item.note)}</div>` : ''}${item.attachments.length ? `<div class="detail-photos">${item.attachments.map(photo => `<a href="${esc(photo.content_url)}" target="_blank" rel="noopener"><img src="${esc(photo.content_url)}" alt="${esc(photo.original_name)}" loading="lazy"></a>`).join('')}</div>` : ''}${caseLink}</div>`;
      }).join('');
      $('#result-detail').showModal();
      if (focusResultId) requestAnimationFrame(() => {
        const target = document.querySelector(`[data-result-card="${CSS.escape(String(focusResultId))}"]`);
        if (target) { target.classList.add('linked-highlight'); target.scrollIntoView({block: 'center', behavior: 'smooth'}); }
      });
    } catch (error) { report(error); }
  }

  const caseStatusLabels = {pending: '待處理', in_progress: '處理中', pending_review: '待複查', closed: '已結案', cancelled: '已取消'};
  const severityLabels = {minor: '輕微', normal: '一般', major: '重大'};
  const historyLabels = {created: '建立案件', assigned: '指派案件', started: '開始處理',
    review_submitted: '送出複查', approved: '複查通過', rejected: '退回改善', cancelled: '取消案件',
    correction_photo_uploaded: '新增改善照片', correction_photo_deleted: '刪除改善照片',
    review_photo_uploaded: '新增複查照片', review_photo_deleted: '刪除複查照片'};
  const isCaseManager = () => ['system_admin', 'inspection_manager'].includes(state.user?.role);

  async function renderCases() {
    const params = new URLSearchParams({page: String(state.casePage), page_size: '20'});
    const filters = {query: '#case-search', status: '#case-status', severity: '#case-severity', overdue: '#case-overdue-filter'};
    for (const [key, selector] of Object.entries(filters)) if ($(selector).value) params.set(key, $(selector).value);
    const [response, summary] = await Promise.all([api(`/abnormal-cases?${params}`), api('/abnormal-cases/summary')]);
    if (state.page !== 'abnormal') return;
    state.cases = response.items;
    const pages = Math.max(1, Math.ceil(response.total / 20));
    if (state.casePage > pages) { state.casePage = pages; return renderCases(); }
    $('#case-pending').textContent = summary.pending;
    $('#case-progress').textContent = summary.in_progress;
    $('#case-review').textContent = summary.pending_review;
    $('#case-overdue').textContent = summary.overdue;
    const start = (state.casePage - 1) * 20;
    $('#case-range').textContent = response.total ? `顯示 ${start + 1}–${start + response.items.length} 件，共 ${response.total} 件` : '目前沒有符合條件的案件';
    $('#case-body').innerHTML = response.items.map(row => `<tr><td class="code">${esc(row.case_number)}</td><td class="title-cell"><strong>${esc(row.location_name)}</strong><div class="sub">${esc(row.item_name)}・${esc(row.title)}</div></td><td><span class="case-severity ${esc(row.severity)}">${esc(severityLabels[row.severity])}</span></td><td>${esc(row.assignee_name || '尚未指派')}</td><td class="${row.is_overdue ? 'overdue' : ''}">${esc(row.due_date || '—')}${row.is_overdue ? '<div class="sub">已逾期</div>' : ''}</td><td><span class="case-status ${esc(row.status)}">${esc(caseStatusLabels[row.status])}</span></td><td style="text-align:right"><button class="quiet" data-case-detail="${esc(row.id)}">查看／處理 →</button></td></tr>`).join('') || '<tr><td colspan="7" class="empty">目前沒有符合條件的異常案件。</td></tr>';
    $('#case-page-label').textContent = `第 ${state.casePage}／${pages} 頁`;
    $('#case-prev').disabled = state.casePage <= 1;
    $('#case-next').disabled = state.casePage >= pages;
  }

  function casePhotos(items, deletable = false) {
    return `<div class="detail-photos">${items.map(photo => `<figure class="photo-thumb"><a href="${esc(photo.content_url)}" target="_blank" rel="noopener"><img src="${esc(photo.content_url)}" alt="${esc(photo.original_name)}" loading="lazy"></a>${deletable ? `<button type="button" data-case-photo-delete="${esc(photo.id)}" aria-label="刪除照片">×</button>` : ''}</figure>`).join('')}</div>`;
  }

  async function openCaseDetail(id) {
    try {
      if (isCaseManager() && !state.assignees.length) state.assignees = (await api('/abnormal-cases/assignees')).items;
      const row = await api(`/abnormal-cases/${encodeURIComponent(id)}`);
      state.currentCase = row;
      const manager = isCaseManager(), assigned = row.assignee_user_id === state.user.id;
      const canWork = manager || assigned;
      const correction = row.attachments.filter(x => x.stage === 'correction');
      const review = row.attachments.filter(x => x.stage === 'review');
      const assignment = manager && ['pending', 'in_progress', 'pending_review'].includes(row.status) ? `<div class="case-block case-actions"><h3>指派與期限</h3><div class="case-action-row"><select id="case-assignee">${state.assignees.map(x => `<option value="${esc(x.id)}" ${x.id === row.assignee_user_id ? 'selected' : ''}>${esc(x.display_name)}${x.department ? `・${esc(x.department)}` : ''}</option>`).join('')}</select><input id="case-due-date" type="date" value="${esc(row.due_date || '')}"><select id="case-severity-edit"><option value="minor" ${row.severity === 'minor' ? 'selected' : ''}>輕微</option><option value="normal" ${row.severity === 'normal' ? 'selected' : ''}>一般</option><option value="major" ${row.severity === 'major' ? 'selected' : ''}>重大</option></select><button class="secondary" data-case-action="assign">儲存指派</button></div></div>` : '';
      let workflow = '';
      if (row.status === 'pending' && canWork) workflow = `<div class="case-block case-actions"><h3>開始改善</h3><p class="sub">需先設定負責人與期限。</p><div class="case-action-row"><button class="primary" data-case-action="start">開始處理</button></div></div>`;
      if (row.status === 'in_progress' && canWork) workflow = `<div class="case-block case-actions"><h3>改善處理</h3><textarea id="case-correction" maxlength="2000" placeholder="請說明改善措施">${esc(row.corrective_action || '')}</textarea><div class="photo-head"><strong>改善照片</strong><small>${correction.length}／5 張${row.severity === 'major' ? '・重大異常至少 1 張' : ''}</small></div>${casePhotos(correction, true)}<label class="photo-add"><input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" data-case-photo="correction"><span>＋</span><small>拍照／選取</small></label><div class="case-action-row"><button class="primary" data-case-action="submit-review">送出複查</button></div></div>`;
      if (row.status === 'pending_review' && manager) workflow = `<div class="case-block case-actions"><h3>複查與結案</h3><div><strong>改善措施</strong><p>${esc(row.corrective_action)}</p></div><textarea id="case-review-note" maxlength="1000" placeholder="填寫複查說明；退回時必填">${esc(row.review_note || '')}</textarea><div class="photo-head"><strong>複查照片</strong><small>${review.length}／5 張</small></div>${casePhotos(review, true)}<label class="photo-add"><input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" data-case-photo="review"><span>＋</span><small>拍照／選取</small></label><div class="case-action-row"><button class="primary" data-case-action="approve">複查通過並結案</button><button class="secondary" data-case-action="reject">退回改善</button></div></div>`;
      const cancel = manager && ['pending', 'in_progress', 'pending_review'].includes(row.status) ? `<div class="case-block case-actions"><h3>其他操作</h3><textarea id="case-cancel-note" maxlength="1000" placeholder="取消原因（必填）"></textarea><div><button class="secondary" data-case-action="cancel">取消案件</button></div></div>` : '';
      $('#case-detail-number').textContent = row.case_number;
      $('#case-detail-content').innerHTML = `<div class="case-grid"><div><span>地點</span><strong>${esc(row.location_name)}（${esc(row.location_code)}）</strong></div><div><span>巡檢項目</span><strong>${esc(row.item_name)}</strong></div><div><span>案件狀態</span><strong>${esc(caseStatusLabels[row.status])}${row.is_overdue ? '・已逾期' : ''}</strong></div><div><span>嚴重度</span><strong>${esc(severityLabels[row.severity])}</strong></div><div><span>負責人</span><strong>${esc(row.assignee_name || '尚未指派')}</strong></div><div><span>預計完成日</span><strong>${esc(row.due_date || '尚未設定')}</strong></div></div><div class="case-block"><div class="case-block-head"><h3>原始異常</h3><button class="quiet" data-linked-inspection="${esc(row.inspection_id)}" data-linked-result="${esc(row.inspection_result_id)}">查看原始巡檢 →</button></div><p class="sub">來源：${esc(row.inspection_number || row.inspection_id)}</p><p>${esc(row.description)}</p>${row.inspection_photos.length ? casePhotos(row.inspection_photos) : '<p class="sub">無現場照片</p>'}</div>${assignment}${workflow}${row.status !== 'in_progress' && correction.length ? `<div class="case-block"><h3>改善照片</h3>${casePhotos(correction)}</div>` : ''}${row.status !== 'pending_review' && review.length ? `<div class="case-block"><h3>複查照片</h3>${casePhotos(review)}</div>` : ''}${row.corrective_action && row.status !== 'pending_review' ? `<div class="case-block"><h3>改善措施</h3><p>${esc(row.corrective_action)}</p></div>` : ''}${row.review_note ? `<div class="case-block"><h3>複查說明</h3><p>${esc(row.review_note)}</p></div>` : ''}${cancel}<div class="case-block"><h3>案件歷程</h3>${row.history.map(h => `<div class="history-row"><time>${esc(dateText(h.created_at))}</time><span>${esc(h.actor_name || '系統')}</span><div><strong>${esc(historyLabels[h.action] || h.action)}</strong>${h.note ? `<div class="sub">${esc(h.note)}</div>` : ''}</div></div>`).join('')}</div>`;
      $('#case-detail').showModal();
    } catch (error) { report(error); }
  }

  async function refreshCurrentCase(message) {
    const id = state.currentCase?.id;
    if (id) await openCaseDetail(id);
    if (state.page === 'abnormal') await renderCases();
    if (message) flash(message);
  }

  async function runCaseAction(action) {
    const row = state.currentCase; if (!row) return;
    try {
      if (action === 'assign') {
        const due = $('#case-due-date').value;
        if (!due) { flash('請設定預計完成日'); return; }
        await patch(`/abnormal-cases/${encodeURIComponent(row.id)}/assignment`, {version: row.version,
          assignee_user_id: $('#case-assignee').value, due_date: due, severity: $('#case-severity-edit').value});
        await refreshCurrentCase('指派資料已更新'); return;
      }
      if (action === 'start') await post(`/abnormal-cases/${encodeURIComponent(row.id)}/start`, {version: row.version, note: ''});
      if (action === 'submit-review') await post(`/abnormal-cases/${encodeURIComponent(row.id)}/submit-review`, {version: row.version, corrective_action: $('#case-correction').value.trim()});
      if (action === 'approve') await post(`/abnormal-cases/${encodeURIComponent(row.id)}/approve`, {version: row.version, note: $('#case-review-note').value.trim()});
      if (action === 'reject') await post(`/abnormal-cases/${encodeURIComponent(row.id)}/reject`, {version: row.version, note: $('#case-review-note').value.trim()});
      if (action === 'cancel') {
        const note = $('#case-cancel-note').value.trim();
        if (!note || !confirm('確定取消此案件嗎？')) return;
        await post(`/abnormal-cases/${encodeURIComponent(row.id)}/cancel`, {version: row.version, note});
      }
      await refreshCurrentCase('案件狀態已更新');
    } catch (error) { report(error); }
  }

  async function uploadCasePhoto(input) {
    const file = input.files?.[0], row = state.currentCase; if (!file || !row) return;
    const data = new FormData(); data.append('photo', file);
    try {
      await api(`/abnormal-cases/${encodeURIComponent(row.id)}/attachments?stage=${encodeURIComponent(input.dataset.casePhoto)}`, {method: 'POST', body: data});
      await refreshCurrentCase('照片已上傳');
    } catch (error) { report(error); }
    finally { input.value = ''; }
  }

  async function deleteCasePhoto(id) {
    if (!confirm('確定刪除此照片嗎？')) return;
    try { await remove(`/abnormal-cases/attachments/${encodeURIComponent(id)}`); await refreshCurrentCase('照片已刪除'); }
    catch (error) { report(error); }
  }

  const taskStatusLabels = {pending: '待執行', in_progress: '執行中', completed: '已完成', cancelled: '已取消'};
  const frequencyLabels = {once: '單次', daily: '每日', weekly: '每週', monthly: '每月'};
  const weekdayLabels = {1: '一', 2: '二', 3: '三', 4: '四', 5: '五', 6: '六', 7: '日'};

  function scheduleRule(row) {
    if (row.frequency === 'weekly') return `每週${row.weekdays.map(x => weekdayLabels[x]).join('、')}`;
    if (row.frequency === 'monthly') return `每月 ${row.day_of_month} 日`;
    return frequencyLabels[row.frequency] || row.frequency;
  }

  async function renderSchedules() {
    if (!$('#task-date-from').value) {
      const start = new Date(), end = new Date(); end.setDate(end.getDate() + 7);
      $('#task-date-from').value = localDateValue(start);
      $('#task-date-to').value = localDateValue(end);
    }
    const params = new URLSearchParams({date_from: $('#task-date-from').value,
      date_to: $('#task-date-to').value, page_size: '100'});
    const query = $('#task-search').value.trim(), status = $('#task-status-filter').value;
    if (query) params.set('query', query);
    if (status) params.set('status', status);
    const manager = ['system_admin', 'inspection_manager'].includes(state.user?.role);
    const requests = [api(`/inspection-tasks?${params}`)];
    if (manager) requests.push(api('/inspection-schedules'), api('/inspection-schedules/assignees'));
    const responses = await Promise.all(requests);
    if (state.page !== 'schedule') return;
    const taskResponse = responses[0];
    state.tasks = taskResponse.items;
    if (manager) {
      state.schedules = responses[1].items;
      state.scheduleAssignees = responses[2].items;
    }
    $('#task-pending').textContent = taskResponse.summary.pending;
    $('#task-progress').textContent = taskResponse.summary.in_progress;
    $('#task-completed').textContent = taskResponse.summary.completed;
    $('#task-overdue').textContent = taskResponse.summary.overdue;
    $('#task-range').textContent = `共 ${taskResponse.total} 件`;
    $('#task-body').innerHTML = state.tasks.map(row => {
      const visualStatus = row.is_overdue ? 'overdue' : row.status;
      const statusLabel = row.is_overdue ? '已逾期' : taskStatusLabels[row.status];
      let action = '';
      if (row.can_start) action = `<button class="primary" data-task-start="${esc(row.id)}">開始巡檢</button>`;
      else if (row.status === 'in_progress' && row.inspection_id && row.assignee_user_id === state.user.id)
        action = `<button class="quiet" data-task-resume="${esc(row.inspection_id)}">繼續巡檢 →</button>`;
      else if (row.status === 'completed' && row.inspection_id)
        action = `<button class="quiet" data-result-detail="${esc(row.inspection_id)}">查看結果 →</button>`;
      return `<tr><td><strong>${esc(row.scheduled_date)}</strong></td><td class="title-cell"><strong>${esc(row.schedule_name)}</strong><div class="sub">${esc(row.location_name)}・${esc(row.location_code)}</div></td><td>${esc(row.assignee_name)}</td><td>${esc(dateText(row.window_start_at))}<div class="sub">截止 ${esc(dateText(row.due_at))}</div></td><td><span class="task-status ${esc(visualStatus)}">${esc(statusLabel)}</span></td><td style="text-align:right">${action || '—'}</td></tr>`;
    }).join('') || '<tr><td colspan="6" class="empty">目前沒有符合條件的巡檢任務。</td></tr>';
    if (manager) {
      $('#schedule-body').innerHTML = state.schedules.map(row => `<tr><td class="title-cell"><strong>${esc(row.name)}</strong><div class="sub">${esc(row.effective_from)}${row.effective_to ? ` ～ ${esc(row.effective_to)}` : ' 起'}</div></td><td>${esc(row.location_name)}</td><td>${esc(row.assignee_name)}</td><td>${esc(scheduleRule(row))}</td><td>${esc(row.start_time)}～${esc(row.due_time)}</td><td><span class="pill ${row.is_active ? '' : 'off'}">${row.is_active ? '啟用' : '停用'}</span></td><td><div class="actions"><button class="quiet" data-action="edit-schedule" data-id="${esc(row.id)}">編輯</button><button class="quiet" data-action="toggle-schedule" data-id="${esc(row.id)}">${row.is_active ? '停用' : '啟用'}</button></div></td></tr>`).join('') || '<tr><td colspan="7" class="empty">尚未建立巡檢排程。</td></tr>';
    }
  }

  function updateScheduleFrequencyFields() {
    const frequency = $('#schedule-form').elements.frequency.value;
    $('#schedule-weekly').classList.toggle('hidden', frequency !== 'weekly');
    $('#schedule-monthly').classList.toggle('hidden', frequency !== 'monthly');
  }

  function openScheduleEditor(id = null) {
    state.editingScheduleId = id;
    const row = state.schedules.find(x => x.id === id);
    const form = $('#schedule-form'); form.reset(); const controls = form.elements;
    $('#schedule-dialog-title').textContent = row ? '編輯巡檢排程' : '新增巡檢排程';
    controls.location_id.innerHTML = state.db.locations.filter(x => x.active || x.id === row?.location_id)
      .map(x => `<option value="${esc(x.id)}">${esc(x.name)}（${esc(x.code)}）</option>`).join('');
    controls.assignee_user_id.innerHTML = state.scheduleAssignees
      .map(x => `<option value="${esc(x.id)}">${esc(x.display_name)}${x.department ? `・${esc(x.department)}` : ''}</option>`).join('');
    controls.name.value = row?.name || '';
    controls.location_id.value = row?.location_id || controls.location_id.options[0]?.value || '';
    controls.assignee_user_id.value = row?.assignee_user_id || controls.assignee_user_id.options[0]?.value || '';
    controls.frequency.value = row?.frequency || 'daily';
    controls.day_of_month.value = row?.day_of_month || 1;
    controls.start_time.value = row?.start_time || '08:00';
    controls.due_time.value = row?.due_time || '17:00';
    controls.effective_from.value = row?.effective_from || localDateValue();
    controls.effective_to.value = row?.effective_to || '';
    controls.is_active.value = String(row?.is_active ?? true);
    form.querySelectorAll('[name="weekday"]').forEach(input => input.checked = (row?.weekdays || [1,2,3,4,5]).includes(Number(input.value)));
    updateScheduleFrequencyFields();
    $('#schedule-dialog').showModal(); controls.name.focus();
  }

  async function saveSchedule(event) {
    event.preventDefault();
    const form = event.currentTarget, controls = form.elements;
    const payload = {name: controls.name.value.trim(), location_id: controls.location_id.value,
      assignee_user_id: controls.assignee_user_id.value, frequency: controls.frequency.value,
      weekdays: [...form.querySelectorAll('[name="weekday"]:checked')].map(x => Number(x.value)),
      day_of_month: controls.frequency.value === 'monthly' ? Number(controls.day_of_month.value) : null,
      start_time: controls.start_time.value, due_time: controls.due_time.value,
      effective_from: controls.effective_from.value, effective_to: controls.effective_to.value || null,
      is_active: controls.is_active.value === 'true'};
    try {
      if (state.editingScheduleId) await patch(`/inspection-schedules/${encodeURIComponent(state.editingScheduleId)}`, payload);
      else await post('/inspection-schedules', payload);
      $('#schedule-dialog').close(); await renderSchedules(); flash('巡檢排程已儲存');
    } catch (error) { report(error); }
  }

  async function startScheduledTask(id) {
    try {
      const response = await post(`/inspection-tasks/${encodeURIComponent(id)}/start`, {});
      state.current = adaptRecord(response.inspection); state.dirty = false;
      await setPage('inspection');
      renderInspectionForm(state.current); showInspectionStep('work');
      window.scrollTo({top: 0, behavior: 'smooth'});
    } catch (error) { report(error); }
  }

  const roleLabels = {system_admin: '系統管理員', inspection_manager: '巡檢管理員',
    inspector: '巡檢人員', viewer: '查詢人員'};
  async function renderUsers() {
    const params = new URLSearchParams();
    const query = $('#user-search').value.trim(), role = $('#user-role-filter').value;
    const active = $('#user-status-filter').value;
    if (query) params.set('query', query);
    if (role) params.set('role', role);
    if (active) params.set('active', active);
    const [users, audit] = await Promise.all([api(`/users?${params}`), api('/audit-logs?limit=100')]);
    if (state.page !== 'users') return;
    state.users = users.items;
    $('#users-body').innerHTML = state.users.map(user => `<tr><td class="title-cell"><strong>${esc(user.display_name)}</strong><div class="sub">${esc(user.username)}${user.email ? ` ・ ${esc(user.email)}` : ''}</div></td><td>${esc(user.department || '—')}</td><td><span class="role-chip">${esc(user.role_label || roleLabels[user.role])}</span></td><td><span class="pill ${user.is_active ? '' : 'off'}">${user.is_active ? '啟用' : '停用'}</span>${user.must_change_password ? '<div class="sub">待修改臨時密碼</div>' : ''}</td><td>${esc(dateText(user.last_login_at))}</td><td><div class="actions"><button class="quiet" data-action="edit-user" data-id="${esc(user.id)}">編輯</button><button class="quiet" data-action="reset-user" data-id="${esc(user.id)}">重設密碼</button><button class="quiet" data-action="revoke-user" data-id="${esc(user.id)}">登出裝置</button><button class="quiet" data-action="toggle-user" data-id="${esc(user.id)}">${user.is_active ? '停用' : '啟用'}</button></div></td></tr>`).join('') || '<tr><td colspan="6" class="empty">沒有符合條件的帳號。</td></tr>';
    $('#audit-list').innerHTML = audit.items.map(row => `<div class="audit-row"><time>${esc(dateText(row.created_at))}</time><span>${esc(row.username || '未知帳號')}</span><strong>${esc(row.summary || row.action)}</strong></div>`).join('') || '<div class="empty">目前沒有操作紀錄。</div>';
  }

  function openUserEditor(id = null) {
    state.editingUserId = id;
    const user = state.users.find(x => x.id === id);
    const form = $('#user-form'); form.reset();
    $('#user-dialog-title').textContent = user ? '編輯帳號' : '新增帳號';
    form.username.disabled = Boolean(user);
    form.username.required = !user;
    form.temporary_password.required = !user;
    $('#temporary-password-field').classList.toggle('hidden', Boolean(user));
    if (user) {
      form.username.value = user.username;
      form.display_name.value = user.display_name;
      form.department.value = user.department || '';
      form.email.value = user.email || '';
      form.role.value = user.role;
      form.is_active.value = String(user.is_active);
    }
    $('#user-dialog').showModal();
    (user ? form.display_name : form.username).focus();
  }

  async function saveUser(event) {
    event.preventDefault();
    const form = event.currentTarget, data = new FormData(form);
    const payload = {display_name: String(data.get('display_name') || '').trim(),
      department: String(data.get('department') || '').trim(), email: String(data.get('email') || '').trim(),
      role: String(data.get('role')), is_active: data.get('is_active') === 'true'};
    if (!state.editingUserId) {
      payload.username = String(data.get('username') || '').trim();
      payload.temporary_password = String(data.get('temporary_password') || '');
    }
    try {
      if (state.editingUserId) await patch(`/users/${encodeURIComponent(state.editingUserId)}`, payload);
      else await post('/users', payload);
      $('#user-dialog').close(); await renderUsers(); flash('帳號資料已儲存');
    } catch (error) { report(error); }
  }

  function openResetPassword(id) {
    const user = state.users.find(x => x.id === id); if (!user) return;
    state.resettingUserId = id; $('#reset-form').reset();
    $('#reset-user-label').textContent = `${user.display_name}（${user.username}）`;
    $('#reset-dialog').showModal(); $('#reset-form').temporary_password.focus();
  }

  async function resetUserPassword(event) {
    event.preventDefault(); const form = event.currentTarget;
    if (form.temporary_password.value !== form.confirmation.value) { flash('兩次輸入的臨時密碼不一致'); return; }
    try {
      await post(`/users/${encodeURIComponent(state.resettingUserId)}/reset-password`, {temporary_password: form.temporary_password.value});
      $('#reset-dialog').close(); await renderUsers(); flash('密碼已重設，使用者下次登入須修改密碼');
    } catch (error) { report(error); }
  }

  document.addEventListener('click', async event => {
    const linkedCase = event.target.closest('[data-linked-case]');
    if (linkedCase) {
      $('#result-detail').close();
      await openCaseDetail(linkedCase.dataset.linkedCase);
      return;
    }
    const linkedInspection = event.target.closest('[data-linked-inspection]');
    if (linkedInspection) {
      $('#case-detail').close();
      await openResultDetail(linkedInspection.dataset.linkedInspection, linkedInspection.dataset.linkedResult);
      return;
    }
    const caseDetail = event.target.closest('[data-case-detail]');
    if (caseDetail) { await openCaseDetail(caseDetail.dataset.caseDetail); return; }
    const caseAction = event.target.closest('[data-case-action]');
    if (caseAction) { await runCaseAction(caseAction.dataset.caseAction); return; }
    const casePhotoDelete = event.target.closest('[data-case-photo-delete]');
    if (casePhotoDelete) { await deleteCasePhoto(casePhotoDelete.dataset.casePhotoDelete); return; }
    const photoDelete = event.target.closest('[data-photo-delete]');
    if (photoDelete) { await deletePhoto(photoDelete.dataset.photoDelete, photoDelete.dataset.itemId); return; }
    const taskStart = event.target.closest('[data-task-start]');
    if (taskStart) { await startScheduledTask(taskStart.dataset.taskStart); return; }
    const taskResume = event.target.closest('[data-task-resume]');
    if (taskResume) { await resumeDraft(taskResume.dataset.taskResume); return; }
    const nav = event.target.closest('[data-page]');
    if (nav) { await setPage(nav.dataset.page); return; }
    const resume = event.target.closest('[data-resume-id]');
    if (resume) { await resumeDraft(resume.dataset.resumeId); return; }
    const detail = event.target.closest('[data-result-detail]');
    if (detail) { await openResultDetail(detail.dataset.resultDetail); return; }
    const inspect = event.target.closest('[data-inspect-location]');
    if (inspect) { await startInspection(inspect.dataset.inspectLocation); return; }
    const select = event.target.closest('[data-select-location]');
    if (select) { state.selected = select.dataset.selectLocation; renderMapping(); return; }
    const button = event.target.closest('[data-action]');
    if (!button) return;
    const {action, id} = button.dataset;
    if (action === 'map') { state.selected = id; await setPage('mapping'); return; }
    if (action === 'edit-location') { openEditor('location', id); return; }
    if (action === 'edit-item') { openEditor('item', id); return; }
    if (action === 'edit-user') { openUserEditor(id); return; }
    if (action === 'edit-schedule') { openScheduleEditor(id); return; }
    if (action === 'toggle-schedule') {
      const schedule = state.schedules.find(x => x.id === id); if (!schedule) return;
      try {
        await patch(`/inspection-schedules/${encodeURIComponent(id)}`, {is_active: !schedule.is_active});
        await renderSchedules(); flash(schedule.is_active ? '排程已停用' : '排程已啟用');
      } catch (error) { report(error); } return;
    }
    if (action === 'reset-user') { openResetPassword(id); return; }
    if (action === 'revoke-user') {
      if (!confirm('確定要登出這個帳號的所有裝置嗎？')) return;
      try { await post(`/users/${encodeURIComponent(id)}/revoke-sessions`, {}); await renderUsers(); flash('已登出該帳號的所有裝置'); }
      catch (error) { report(error); } return;
    }
    if (action === 'toggle-user') {
      const user = state.users.find(x => x.id === id); if (!user) return;
      if (!confirm(`確定要${user.is_active ? '停用' : '啟用'} ${user.display_name} 的帳號嗎？`)) return;
      try { await patch(`/users/${encodeURIComponent(id)}`, {is_active: !user.is_active}); await renderUsers(); flash(user.is_active ? '帳號已停用' : '帳號已啟用'); }
      catch (error) { report(error); } return;
    }
    if (action === 'toggle-location' || action === 'toggle-item') {
      const isLocation = action === 'toggle-location';
      const item = (isLocation ? state.db.locations : state.db.items).find(x => x.id === id);
      if (!item) return;
      try {
        await patch(`/${isLocation ? 'locations' : 'items'}/${encodeURIComponent(id)}`, {is_active: !item.active});
        await loadBootstrap(); renderMaintenance(); flash(item.active ? '已停用' : '已啟用');
      } catch (error) { report(error); }
    }
  });
  document.addEventListener('change', async event => {
    if (event.target.dataset.casePhoto) { await uploadCasePhoto(event.target); return; }
    if (event.target.dataset.photoInput) { await uploadPhoto(event.target.dataset.photoInput, event.target); return; }
    const itemId = event.target.dataset.mapSelect || event.target.dataset.mapRequired || event.target.dataset.mapOrder;
    if (itemId) { await updateMapping(event.target); return; }
    if (event.target.dataset.inspectResult && state.current) {
      const result = state.current.results.find(x => x.itemId === event.target.dataset.inspectResult);
      if (result) { result.result = event.target.value; markDirty(); renderInspectionForm(state.current); }
    }
  });
  document.addEventListener('input', event => {
    if (state.current) {
      if (event.target.id === 'inspector-name') { state.current.inspector = event.target.value; markDirty(); }
      if (event.target.dataset.inspectNote) {
        const result = state.current.results.find(x => x.itemId === event.target.dataset.inspectNote);
        if (result) { result.note = event.target.value; markDirty(); }
      }
    }
  });
  for (const id of ['location-search', 'item-search', 'mapping-search', 'inspection-search'])
    $('#' + id).addEventListener('input', () => {
      if (id === 'location-search') renderLocations();
      if (id === 'item-search') renderItems();
      if (id === 'mapping-search') renderMapping();
      if (id === 'inspection-search') renderInspectionLocations();
    });
  for (const id of ['location-filter', 'item-filter', 'mapping-filter'])
    $('#' + id).addEventListener('change', () => {
      if (id === 'location-filter') renderLocations();
      if (id === 'item-filter') renderItems();
      if (id === 'mapping-filter') renderMapping();
    });
  $('#create-button').addEventListener('click', () => {
    if (state.page === 'users') openUserEditor();
    else if (state.page === 'schedule') openScheduleEditor();
    else openEditor(state.page === 'locations' ? 'location' : 'item');
  });
  $('#edit-form').addEventListener('submit', saveEditor);
  $('#close-editor').addEventListener('click', () => $('#editor').close());
  $('#cancel-editor').addEventListener('click', () => $('#editor').close());
  $('#user-form').addEventListener('submit', saveUser);
  $('#close-user-dialog').addEventListener('click', () => $('#user-dialog').close());
  $('#cancel-user-dialog').addEventListener('click', () => $('#user-dialog').close());
  $('#reset-form').addEventListener('submit', resetUserPassword);
  $('#close-reset-dialog').addEventListener('click', () => $('#reset-dialog').close());
  $('#cancel-reset-dialog').addEventListener('click', () => $('#reset-dialog').close());
  $('#schedule-form').addEventListener('submit', saveSchedule);
  $('#schedule-form').elements.frequency.addEventListener('change', updateScheduleFrequencyFields);
  $('#close-schedule-dialog').addEventListener('click', () => $('#schedule-dialog').close());
  $('#cancel-schedule-dialog').addEventListener('click', () => $('#schedule-dialog').close());
  for (const id of ['task-search', 'task-date-from', 'task-date-to', 'task-status-filter'])
    $('#' + id).addEventListener(id === 'task-search' ? 'input' : 'change', () => renderSchedules().catch(report));
  $('#task-clear').addEventListener('click', () => {
    $('#task-search').value = ''; $('#task-status-filter').value = '';
    $('#task-date-from').value = ''; $('#task-date-to').value = '';
    renderSchedules().catch(report);
  });
  for (const id of ['user-search', 'user-role-filter', 'user-status-filter'])
    $('#' + id).addEventListener(id === 'user-search' ? 'input' : 'change', () => renderUsers().catch(report));
  for (const id of ['case-search', 'case-status', 'case-severity', 'case-overdue-filter'])
    $('#' + id).addEventListener(id === 'case-search' ? 'input' : 'change', () => {
      state.casePage = 1; renderCases().catch(report);
    });
  $('#case-clear').addEventListener('click', () => {
    for (const id of ['case-search', 'case-status', 'case-severity', 'case-overdue-filter']) $('#' + id).value = '';
    state.casePage = 1; renderCases().catch(report);
  });
  $('#case-prev').addEventListener('click', () => { if (state.casePage > 1) { state.casePage--; renderCases().catch(report); } });
  $('#case-next').addEventListener('click', () => { state.casePage++; renderCases().catch(report); });
  $('#close-case-detail').addEventListener('click', () => $('#case-detail').close());
  $('#case-detail-done').addEventListener('click', () => $('#case-detail').close());
  $('#inspection-back').addEventListener('click', leaveInspection);
  $('#inspection-save').addEventListener('click', async () => {
    try { await persistDraft(); flash('巡檢草稿已儲存在伺服器'); } catch (error) { report(error); }
  });
  $('#inspection-review').addEventListener('click', reviewInspection);
  $('#inspection-confirm-back').addEventListener('click', () => $('#inspection-confirm').close());
  $('#close-inspection-confirm').addEventListener('click', () => $('#inspection-confirm').close());
  $('#inspection-confirm-submit').addEventListener('click', submitInspection);
  $('#inspection-new').addEventListener('click', async () => {
    await loadDrafts(); showInspectionStep('pick'); renderInspectionLocations();
  });
  $('#inspection-show-result').addEventListener('click', () => setPage('results'));
  for (const id of ['result-search', 'result-date-from', 'result-date-to', 'result-location', 'result-status']) {
    $('#' + id).addEventListener(id === 'result-search' ? 'input' : 'change', async () => {
      state.resultPage = 1;
      try { await renderResults(); } catch (error) { report(error); }
    });
  }
  $('#result-clear').addEventListener('click', () => {
    for (const id of ['result-search', 'result-date-from', 'result-date-to', 'result-location', 'result-status']) $('#' + id).value = '';
    state.resultPage = 1; renderResults().catch(report);
  });
  $('#result-prev').addEventListener('click', () => { if (state.resultPage > 1) { state.resultPage--; renderResults().catch(report); } });
  $('#result-next').addEventListener('click', () => { state.resultPage++; renderResults().catch(report); });
  $('#close-result-detail').addEventListener('click', () => $('#result-detail').close());
  $('#detail-done').addEventListener('click', () => $('#result-detail').close());
  $('#logout').addEventListener('click', async () => {
    try { await post('/auth/logout', {}); } finally { location.replace('/login'); }
  });
  $('#change-password').addEventListener('click', () => {
    $('#password-form').reset();
    $('#password-dialog').showModal();
    $('#current-password').focus();
  });
  $('#close-password').addEventListener('click', () => $('#password-dialog').close());
  $('#cancel-password').addEventListener('click', () => $('#password-dialog').close());
  $('#password-form').addEventListener('submit', async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const currentPassword = String(form.get('current_password') || '');
    const newPassword = String(form.get('new_password') || '');
    const confirmation = String(form.get('confirm_password') || '');
    if (newPassword !== confirmation) { flash('兩次輸入的新密碼不一致'); return; }
    if (newPassword.length < 10) { flash('新密碼至少需要 10 個字元'); return; }
    try {
      const response = await post('/auth/change-password', {current_password: currentPassword, new_password: newPassword});
      state.user = response.user;
      $('#password-dialog').close();
      $('#close-password').classList.remove('hidden');
      $('#cancel-password').classList.remove('hidden');
      flash('密碼已更新');
      await setPage('home');
    } catch (error) { report(error); }
  });
  window.addEventListener('beforeunload', event => {
    if (state.dirty) { event.preventDefault(); event.returnValue = ''; }
  });
  loadCurrentUser().then(() => setPage('home')).catch(report);
})();
