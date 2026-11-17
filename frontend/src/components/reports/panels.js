import {reports} from '../../api/entities.js';
import {esc, date} from '../../utils/dom.js';
import {TIMEZONES, WORKDAYS, WEEKDAY_LABEL} from '../../constants/zones.js';

const SLOT_STATUS = {
  pending: ['待派送', 'status-pending'],
  delivered: ['已派送', 'status-delivered'],
  skipped: ['已跳过', 'status-skipped'],
};

function versionBadge(v) {
  return `<span class="version-tag">v${v.version_no}</span>`;
}

function versionSummary(r) {
  if (r.schedule_mode !== 'calendar' || !r.versions || !r.versions.length) return '';
  const v = r.versions[r.versions.length - 1];
  const days = v.workdays.map(w => WEEKDAY_LABEL[w]).join('、');
  return `<p>${esc(v.timezone)} · ${days} · ${esc(v.handover_time)} 当地交班
    ${v.paused_dates.length ? ` · 停工 ${v.paused_dates.length} 天` : ''}</p>
    <small>当前 ${versionBadge(v)} 生效于 ${v.effective_from ? date(v.effective_from) : '建表即生效'} · 共 ${r.versions.length} 个版本</small>`;
}

function intervalSummary(r) {
  return `<p>固定秒间隔 · 每 ${r.interval_seconds} 秒一轮</p>
    <small>下次 ${r.next_run ? date(r.next_run) : '—'}</small>`;
}

export function previewTable(preview) {
  if (!preview) return '<p class="empty">填写班历后点击“预览未来交班”。</p>';
  if (!preview.shifts.length) return '<p class="empty">该窗口内没有符合工作日的场次。</p>';
  return `<div class="table-wrap preview-table"><table>
    <thead><tr><th>当地日期</th><th>星期</th><th>交班时刻</th><th>UTC 时刻</th><th>夏令时处理</th></tr></thead>
    <tbody>${preview.shifts.map(s => `<tr>
      <td>${esc(s.slot_date)}</td><td>${esc(s.weekday_label)}</td>
      <td>${esc(s.local_time)}</td>
      <td>${s.scheduled_at ? date(s.scheduled_at) : '—'}</td>
      <td><span class="slot-status ${SLOT_STATUS[s.status]?.[1] || ''}">${
        s.status === 'gap' ? '跳过：当地无此时刻' : s.status === 'ambiguous' ? '取首次出现' : '正常'
      }</span></td></tr>`).join('')}</tbody></table></div>`;
}

export function schedulePanel(list, admin) {
  const calendar = list.filter(r => r.schedule_mode === 'calendar');
  const legacy = list.filter(r => r.schedule_mode === 'interval');
  return `<section>
    <div class="section-title"><h2>班历分发计划</h2><span>${calendar.length} 条按当地交班</span></div>
    <div class="schedule-list">${calendar.map(r => `<article class="schedule-card" data-report-card="${r.id}">
      <div>
        <div class="schedule-head"><strong>${esc(r.name)}</strong>
          <span class="mode-tag">当地班历</span>${versionBadge(r.versions?.at(-1) || {version_no: 1})}
          <span class="slot-status ${r.enabled ? 'status-delivered' : 'status-skipped'}">${r.enabled ? '启用中' : '已暂停'}</span></div>
        <p>${esc(r.destination)}</p>
        ${versionSummary(r)}
        <small>下场 ${r.next_run ? date(r.next_run) : '窗口内暂无待派场次'}</small>
      </div>
      <div class="card-actions">
        <button class="button small" data-trace="${r.id}">追查场次</button>
        ${admin ? `<button class="button small" data-adjust="${r.id}">调整班历</button>
        <button class="button small" data-toggle="${r.id}">${r.enabled ? '暂停' : '启用'}</button>` : ''}
      </div></article>`).join('') || '<p class="empty">还没有按当地时区交班的计划。</p>'}
    </div>
    <div class="section-title compact-title"><h2>原秒间隔计划（继续可用）</h2><span>${legacy.length} 条</span></div>
    <div class="schedule-list">${legacy.map(r => `<article>
      <div><strong>${esc(r.name)}</strong>
        <span class="slot-status ${r.enabled ? 'status-delivered' : 'status-skipped'}">${r.enabled ? '启用中' : '已暂停'}</span>
        ${intervalSummary(r)}</div>
      ${admin ? `<button class="button small" data-toggle="${r.id}">${r.enabled ? '暂停' : '启用'}</button>` : ''}
    </article>`).join('') || '<p class="empty">暂无旧版计划。</p>'}</div>
  </section>`;
}

export function inboxPanel(deliveries) {
  return `<section class="panel inbox"><div class="section-title">
    <h2>本地收件箱 · 全局留档</h2><span>${deliveries.length} 份归档</span></div>
    ${deliveries.map(d => `<div class="delivery">
      <div><strong>${esc(d.filename)}</strong>
        <p>${esc(d.destination)} · ${date(d.created_at)}</p>
        <small>${d.schedule_mode === 'calendar'
          ? `班历场次 · 版本记录 ${d.version_id ?? '—'} · ` : '秒间隔计划 · '}
          SHA256 ${esc(d.checksum.slice(0, 24))}…</small></div>
      <div><button class="text-button" data-download="${d.id}" data-format="csv">CSV ↓</button>
      <button class="text-button" data-download="${d.id}" data-format="json">JSON ↓</button></div>
    </div>`).join('') || '<p class="empty">计划执行后，文件会出现在此处。等待片刻后刷新。</p>'}</section>`;
}

export function traceView(report, slots, deliveries) {
  const deliveredMap = new Map(deliveries.map(d => [d.slot_id, d]));
  const counts = slots.reduce((acc, s) => { acc[s.status] = (acc[s.status] || 0) + 1; return acc; }, {});
  return `<section class="panel trace-panel">
    <div class="section-title"><h2>场次追查 · ${esc(report.name)}</h2>
      <span>待派 ${counts.pending || 0} · 已派 ${counts.delivered || 0} · 跳过 ${counts.skipped || 0}</span></div>
    <div class="trace-filters">
      <button class="button small" data-slot-filter="" data-report="${report.id}">全部</button>
      <button class="button small" data-slot-filter="pending" data-report="${report.id}">仅欠发</button>
      <button class="button small" data-slot-filter="delivered" data-report="${report.id}">仅已派</button>
      <button class="button small" data-slot-filter="skipped" data-report="${report.id}">仅跳过</button>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>场次（当地）</th><th>UTC 时刻</th><th>归属版本</th><th>状态</th><th>夏令时/失败说明</th><th>归档</th></tr></thead>
      <tbody>${slots.map(s => {
        const d = deliveredMap.get(s.id);
        const [label, cls] = SLOT_STATUS[s.status] || [s.status, ''];
        return `<tr>
          <td>${esc(s.slot_key)}</td>
          <td>${s.scheduled_at ? date(s.scheduled_at) : '—'}</td>
          <td>${versionBadge({version_no: report.versions?.find(v => v.id === s.version_id)?.version_no || '?'})}</td>
          <td><span class="slot-status ${cls}">${label}</span></td>
          <td>${esc(s.last_error || s.dst_note || '—')}</td>
          <td>${d ? `<button class="text-button" data-download="${d.id}" data-format="csv">CSV ↓</button>
                 <button class="text-button" data-download="${d.id}" data-format="json">JSON ↓</button>` : '—'}</td>
        </tr>`;
      }).join('')}</tbody></table></div>
    <button class="button small" data-back="${report.id}">返回计划列表</button>
  </section>`;
}

export function adjustView(report, versions) {
  const v = versions[versions.length - 1];
  const minDate = new Date(Date.now() + 60000 - new Date().getTimezoneOffset() * 60000)
    .toISOString().slice(0, 16);
  return `<section class="panel adjust-panel">
    <div class="section-title"><h2>调整班历 · ${esc(report.name)}</h2><span>新版本指定生效时间</span></div>
    <div class="version-history">${versions.map(x => `<div class="version-row">
      ${versionBadge(x)}<span>${esc(x.timezone)} · ${esc(x.handover_time)} ·
      ${x.workdays.map(w => WEEKDAY_LABEL[w]).join('、')}</span>
      <small>${x.effective_from ? '生效 ' + date(x.effective_from) : '建表即生效'} · ${esc(x.note)}</small>
    </div>`).join('')}</div>
    <p class="hint">生效时间之前已到期但未派送的场次，仍按旧版补齐；生效之后按新版登记。每个交班场次只归属一个版本，不会漏场或双发。</p>
    <form id="adjust-form" data-report="${report.id}">
      <label>时区<select name="timezone">${TIMEZONES.map(([val, label]) =>
        `<option value="${val}" ${val === v.timezone ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select></label>
      <label>工作日（当地）<div class="weekday-grid">${WORKDAYS.map(([key, label]) =>
        `<label class="check"><input type="checkbox" name="workdays" value="${key}" ${v.workdays.includes(key) ? 'checked' : ''}>${label}</label>`).join('')}</div></label>
      <div class="parameter-grid">
        <label>交班时刻<input type="time" name="handover_time" value="${esc(v.handover_time)}" required></label>
        <label>生效时间（本机时区，按 UTC 留痕）<input type="datetime-local" name="effective_local" min="${minDate}" required></label>
      </div>
      <label>停工日期（逗号分隔 YYYY-MM-DD，留空无停工）
        <input name="paused_dates" value="${esc(v.paused_dates.join(', '))}" placeholder="2026-12-25, 2027-01-01"></label>
      <label>调整说明<input name="note" value="班历调整" maxlength="300"></label>
      <button type="submit" class="primary">登记新版本</button>
    </form>
    <button class="button small" data-back="${report.id}">返回计划列表</button>
  </section>`;
}

export function createPanel(approved, initialPreview) {
  return `<section class="panel"><div class="section-title"><h2>创建分发计划</h2></div>
    <form id="report-form">
      <label>简报名称<input name="name" required minlength="2" value="海外烧成组交班简报"></label>
      <label>已批准分析<select name="job_id" required>${approved.map(j =>
        `<option value="${j.id}">${esc(j.name)}</option>`).join('')}</select></label>
      <label>业务接收组<input name="destination" value="海外烧成组 · 当地收件箱" required></label>
      <label>计划方式<select name="schedule_mode" id="schedule-mode">
        <option value="calendar">当地班历（时区 / 工作日 / 交班时刻）</option>
        <option value="interval">固定秒间隔（原方式）</option>
      </select></label>
      <div id="calendar-fields">
        <div class="parameter-grid">
          <label>时区<select name="timezone">${TIMEZONES.map(([val, label]) =>
            `<option value="${val}" ${val === 'Europe/Berlin' ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select></label>
          <label>起始日期<input type="date" name="start_date" required></label>
        </div>
        <label>工作日（当地）<div class="weekday-grid">${WORKDAYS.map(([key, label], i) =>
          `<label class="check"><input type="checkbox" name="workdays" value="${key}" ${i < 5 ? 'checked' : ''}>${label}</label>`).join('')}</div></label>
        <div class="parameter-grid">
          <label>交班时刻（当地）<input type="time" name="handover_time" value="07:00" required></label>
          <label>停工日期<input name="paused_dates" placeholder="2026-12-25, 2027-01-01"></label>
        </div>
        <button type="button" class="button" id="preview-btn">预览未来交班 ↻</button>
        <div id="preview-box" class="preview-box">${previewTable(initialPreview)}</div>
      </div>
      <div id="interval-fields" hidden>
        <div class="parameter-grid">
          <label>分发周期<select name="interval_seconds">
            <option value="86400">每日</option><option value="604800">每周</option>
            <option value="60">每分钟（验收）</option></select></label>
          <label>首次执行<select name="delay_seconds">
            <option value="0">立即</option><option value="60">1 分钟后</option>
            <option value="3600">1 小时后</option></select></label>
        </div>
      </div>
      <button type="submit" class="primary" ${approved.length ? '' : 'disabled'}>保存分发计划</button>
    </form>
    <p class="hint">停工日期不派送；夏令时跳过不存在的当地时刻，回拨重复时刻取首次。仅负责人可创建、暂停或调整。</p>
  </section>`;
}
