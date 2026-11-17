import {jobs, reports} from '../api/entities.js';
import {download} from '../api/client.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {localInputToUtc, todayInput} from '../constants/zones.js';
import {createPanel, schedulePanel, traceView, adjustView, previewTable, inboxPanel} from '../components/reports/panels.js';

const state = {view: 'list', traceId: null, slotFilter: '', preview: null};

function parsePaused(value) {
  return String(value || '').split(',').map(s => s.trim()).filter(Boolean);
}

function collectCalendar(form) {
  return {
    timezone: form.get('timezone'),
    workdays: form.getAll('workdays'),
    handover_time: form.get('handover_time'),
    paused_dates: parsePaused(form.get('paused_dates')),
    start_date: form.get('start_date'),
  };
}

export async function reportPage() {
  const [list, deliveries, allJobs] = await Promise.all([
    reports.list(), reports.deliveries(), jobs.list()]);
  workspace.reports = list;
  workspace.deliveries = deliveries;
  const approved = allJobs.filter(j => j.approved && j.status === 'completed');
  const admin = session.user.role === 'admin';
  let body;
  if (state.view === 'trace') {
    const report = list.find(r => r.id === state.traceId);
    if (!report) { state.view = 'list'; return reportPage(); }
    const [slots, dls] = await Promise.all([
      reports.slots(report.id, state.slotFilter),
      reports.deliveries(report.id)]);
    body = createPanel(approved, state.preview) + traceView(report, slots, dls);
  } else if (state.view === 'adjust') {
    const report = list.find(r => r.id === state.traceId);
    if (!report || report.schedule_mode !== 'calendar') { state.view = 'list'; return reportPage(); }
    const versions = await reports.versions(report.id);
    body = createPanel(approved, state.preview) + adjustView(report, versions);
  } else {
    body = createPanel(approved, state.preview)
      + `<div>${schedulePanel(list, admin)}${inboxPanel(deliveries)}</div>`;
  }
  return heading('05 / DISTRIBUTION', '定时分发与归档',
    '按当地时区、工作日与交班时刻派送；停工不发，夏令时自动跳过或取首次，场次与版本全程可追溯。',
    '<button class="button" id="refresh-reports">刷新收件箱 ↻</button>')
    + `<div class="report-grid">${body}</div>`
    + (admin ? '' : '<p class="hint">当前角色只读：创建、暂停与调整班历仅业务负责人可操作。</p>');
}

async function openTrace(id, filter = '') {
  state.view = 'trace'; state.traceId = id; state.slotFilter = filter;
  await render();
}

let render;
export function bindReports(refresh) {
  render = refresh;
  document.querySelector('#refresh-reports').onclick = refresh;

  // 计划方式切换
  const mode = document.querySelector('#schedule-mode');
  if (mode) {
    const start = document.querySelector('input[name=start_date]');
    if (start && !start.value) start.value = todayInput();
    mode.onchange = () => {
      const cal = document.querySelector('#calendar-fields');
      const leg = document.querySelector('#interval-fields');
      const isCal = mode.value === 'calendar';
      cal.hidden = !isCal; leg.hidden = isCal;
    };
  }

  // 预览未来交班
  const previewBtn = document.querySelector('#preview-btn');
  if (previewBtn) {
    previewBtn.onclick = async () => {
      const form = document.querySelector('#report-form');
      const cal = collectCalendar(form);
      if (!cal.workdays.length) return notify('请至少选择一个工作日', true);
      try {
        state.preview = await reports.preview({
          ...cal, days: 21,
          start_date: cal.start_date || todayInput()});
        document.querySelector('#preview-box').innerHTML = previewTable(state.preview);
        notify(`已预览 ${state.preview.shifts.length} 个未来交班场次`);
      } catch (e) { notify(e.message, true); }
    };
  }

  // 创建计划
  const form = document.querySelector('#report-form');
  if (form) {
    submit(form, async f => {
      const modeValue = f.get('schedule_mode');
      const payload = {
        name: f.get('name'), job_id: Number(f.get('job_id')),
        destination: f.get('destination'), schedule_mode: modeValue,
      };
      if (modeValue === 'calendar') {
        Object.assign(payload, collectCalendar(f), {note: '初始班历'});
      } else {
        payload.interval_seconds = Number(f.get('interval_seconds'));
        payload.delay_seconds = Number(f.get('delay_seconds'));
      }
      await reports.create(payload);
      state.preview = null;
      notify('计划已保存：场次按当地班历登记，后台 worker 到期自动归档');
      state.view = 'list';
      await refresh();
    });
  }

  // 计划卡片：追查 / 调整
  document.querySelectorAll('[data-trace]').forEach(b =>
    b.onclick = () => openTrace(Number(b.dataset.trace)));
  document.querySelectorAll('[data-adjust]').forEach(b => {
    b.onclick = () => { state.view = 'adjust'; state.traceId = Number(b.dataset.adjust); refresh(); };
  });
  document.querySelectorAll('[data-back]').forEach(b =>
    b.onclick = () => { state.view = 'list'; state.traceId = null; refresh(); });
  document.querySelectorAll('[data-slot-filter]').forEach(b =>
    b.onclick = () => openTrace(Number(b.dataset.report), b.dataset.slotFilter));
  document.querySelectorAll('[data-toggle]').forEach(b =>
    b.onclick = async () => {
      try { await reports.toggle(Number(b.dataset.toggle)); await refresh(); }
      catch (e) { notify(e.message, true); }
    });

  // 调整班历表单
  const adjustForm = document.querySelector('#adjust-form');
  if (adjustForm) {
    submit(adjustForm, async f => {
      const effective_from = localInputToUtc(f.get('effective_local'));
      if (!effective_from) return notify('请选择生效时间', true);
      const workdays = f.getAll('workdays');
      if (!workdays.length) return notify('请至少选择一个工作日', true);
      await reports.adjust(Number(adjustForm.dataset.report), {
        timezone: f.get('timezone'), workdays,
        handover_time: f.get('handover_time'),
        paused_dates: parsePaused(f.get('paused_dates')),
        effective_from, note: f.get('note') || '班历调整',
      });
      notify('新版本已登记，生效前欠发按旧版补齐，之后按新版派送');
      state.view = 'list';
      await refresh();
    });
  }

  document.querySelectorAll('[data-download]').forEach(b =>
    b.onclick = () => download(b.dataset.download, b.dataset.format)
      .catch(e => notify(e.message, true)));
}
