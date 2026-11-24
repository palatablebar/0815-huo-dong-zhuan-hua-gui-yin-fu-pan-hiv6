import {element, pretty} from './client.js';

const labels = {
  READY:'通过', MISMATCH:'差异待复核', PENDING:'待复核', APPROVED:'已签发', HELD:'已暂缓',
  MULTI_TOUCH:'多触点', DIRECT_ONLY:'仅直达', NO_TOUCH:'无触点'
};

const views = {
  ledger: {title:'归因账', headers:['转化', '净额', '渠道功劳', '直达/无触点专列', '模式', '对平']},
  direct: {title:'直达记录', headers:['触点', '转化', '渠道', '提前分钟', '计入']},
  no_touch: {title:'无触点案例', headers:['转化', '净额', '参考值', '排除触点']},
  issues: {title:'阻断项', headers:['类别', '记录键', '分组', '说明']}
};

export function badge(status) {
  return element('span', labels[status] || status, {class:'badge', 'data-result':status, title: status});
}

function cell(text) { return element('td', text === undefined || text === null ? '—' : String(text)); }

function issueText(issue) {
  if (issue.detail) return issue.detail;
  if (issue.reason) return issue.reason;
  return '';
}

function fillLedger(body, report) {
  const entries = report.reconciliation?.entries || report.ledger?.entries || [];
  for (const row of entries) {
    const tr = body.insertRow();
    const button = element('button', row.record, {type:'button', 'data-case':row.case, 'data-record':row.record});
    tr.insertCell().append(button);
    const separate = row.separate_cents ?? ((row.direct_cents || 0) + (row.no_touch_cents || 0));
    const settled = row.reconciled ?? (row.channel_credit_cents === row.net_cents);
    tr.append(cell(row.net_cents), cell(row.channel_credit_cents), cell(separate),
      cell(labels[row.mode] || row.mode));
    tr.insertCell().append(badge(settled ? 'READY' : 'MISMATCH'));
  }
  if (!entries.length) body.insertRow().insertCell().textContent = '当前批次没有转化记录';
}

function fillDirect(body, report) {
  const records = report.direct || [];
  for (const row of records) {
    const tr = body.insertRow();
    tr.append(cell(row.record), cell(row.conversion), cell(row.channel),
      cell(row.minutes_before), cell(row.credited ? '是' : '否 · 直达'));
  }
  if (!records.length) body.insertRow().insertCell().textContent = '没有直达记录';
}

function fillNoTouch(body, report) {
  const records = report.no_touch || [];
  for (const row of records) {
    const tr = body.insertRow();
    const excluded = (row.excluded || []).map(item => `${item.record}·${item.reason}`).join('；') || '窗口内无记录';
    tr.append(cell(row.record), cell(row.net_cents), cell(row.expected_cents), cell(excluded));
  }
  if (!records.length) body.insertRow().insertCell().textContent = '没有无触点案例';
}

function fillIssues(body, report) {
  const issues = report.issues || [];
  for (const issue of issues) {
    const tr = body.insertRow();
    const kind = issue.blocking ? issue.kind : `${issue.kind}（仅列示）`;
    tr.append(cell(kind), cell(issue.record), cell(issue.case), cell(issueText(issue)));
  }
  if (!issues.length) body.insertRow().insertCell().textContent = '没有阻断项';
}

export function snapshot(report, selected, stage, tab = 'ledger') {
  const stats = report.intake;
  document.querySelector('[data-metric="input"]').textContent = stats.input;
  document.querySelector('[data-metric="accepted"]').textContent = stats.accepted;
  document.querySelector('[data-metric="isolated"]').textContent = stats.rejected;
  document.querySelector('[data-metric="cases"]').textContent = report.cases?.length ?? '—';
  const table = document.querySelector('#rows');
  table.replaceChildren();
  const head = element('tr');
  const body = table.createTBody();
  if (stage === 'intake') {
    head.append(...['源行', '记录键', '业务分组', '原因码'].map(title => element('th', title, {scope:'col'})));
    for (const item of stats.isolation) {
      const tr = body.insertRow();
      tr.append(...[item.line,item.record,item.case,item.reason].map(value=>cell(value)));
    }
    if (!stats.isolation.length) body.insertRow().insertCell().textContent = '当前文件没有隔离行';
    document.querySelector('#panel-title').textContent = '样例采信';
  } else if (stage === 'balance' || report.reconciliation) {
    const view = views[tab] || views.ledger;
    head.append(...view.headers.map(title => element('th', title, {scope:'col'})));
    ({ledger: fillLedger, direct: fillDirect, no_touch: fillNoTouch, issues: fillIssues})[tab](body, report);
    document.querySelector('#panel-title').textContent = view.title;
  } else {
    head.append(...['业务分组', '输入行', '计算值', '参考值', '判定'].map(title => element('th', title, {scope:'col'})));
    for (const row of report.cases || []) {
      const tr = body.insertRow();
      const button = element('button', row.case, {type:'button','data-case':row.case,'aria-pressed':String(row.case===selected)});
      tr.insertCell().append(button);
      [row.records.length, row.measure?.value ?? '—', row.measure?.expected ?? '—'].forEach(value=>tr.insertCell().textContent=value);
      tr.insertCell().append(badge(row.status));
    }
    document.querySelector('#panel-title').textContent = '阶段结果';
  }
  table.createTHead().append(head);
  const picked = report.cases?.find(row=>row.case===selected);
  document.querySelector('#detail-title').textContent = picked ? `分组 ${picked.case} · 归因账` : '采信摘要';
  const shown = picked
    ? picked.attribution ?? picked.measure?.attribution ?? picked.prep?.details ?? {原因:picked.status}
    : stats.reasons;
  document.querySelector('#detail').textContent = pretty(shown);
  const balance = report.balance;
  if (balance) {
    const books = balance.reconciliation || report.reconciliation || {};
    document.querySelector('#counts').textContent =
      `行数 ${balance.accounted}/${balance.input} · 净额 ${books.total_net_cents ?? '—'} 分 · ` +
      `渠道 ${books.channel_credit_cents ?? '—'} 分 · ` +
      `专列 ${books.separate_cents ?? 0} 分 · ` +
      `阻断 ${balance.blocking?.length ?? 0} 条` +
      (balance.releasable ? ' · 可签发' : ' · 不可签发');
  } else {
    document.querySelector('#counts').textContent = `采信 ${stats.accepted} 行 · 隔离 ${stats.rejected} 行`;
  }
}

export function history(items, active) {
  const target = document.querySelector('#history');
  target.replaceChildren();
  for (const run of items) {
    const button = element('button', run.id.slice(0,10), {'data-run':run.id,'aria-pressed':String(run.id===active),type:'button'});
    const item = element('li');
    item.append(button, badge(run.status));
    target.append(item);
  }
  if (!items.length) target.append(element('li','尚无执行批次'));
}
