import {element} from './client.js';

function zone(target, className, text) {
  const box = element('div', undefined, {class:className});
  if (text) box.append(element('span',text));
  target.append(box);
  return box;
}

export function visualize(report, selected) {
  const target = document.querySelector('#visual');
  const row = report.cases?.find(item => item.case === selected);
  target.replaceChildren();
  const books = row?.attribution ?? row?.measure?.attribution;
  if (!books) { target.append(element('p','该分组暂无归因账')); return; }
  const scene = zone(target, 'touch-scene');
  zone(scene, 'touch-chip', `净额 ${books.net_cents} 分`);
  const route = element('div', 'touch-length', books.mode === 'MULTI_TOUCH'
    ? `${books.allocations.length} 个触点等分 · 窗口 ${books.window.start}–${books.window.end}`
    : books.mode === 'DIRECT_ONLY' ? '仅直达触点 · 不计渠道功劳' : '窗口内无同意触点');
  scene.append(route);
  zone(scene, 'conversion-chip', books.mode === 'MULTI_TOUCH'
    ? `渠道 ${books.channel_credit_cents} 分` : '渠道 0 分');
  const max = Math.max(1, ...(books.channels || []).map(item => item.credit_cents));
  for (const channel of books.channels || []) {
    const line = element('div', 'touch-key');
    const bar = element('div', 'mark-piece');
    bar.style.setProperty('--part', `${Math.max(0, Math.min(100, 100*channel.credit_cents/max))}%`);
    line.append(element('span', `渠道 ${channel.channel} · ${channel.credit_cents} 分 · ${channel.touches.join('、')}`), bar);
    target.append(line);
  }
  if (books.mode !== 'MULTI_TOUCH') {
    target.append(element('p', books.mode === 'DIRECT_ONLY'
      ? '直达记录单独列示，净额不落到渠道，列为未对平。'
      : '无触点案例单独列示，净额无法归因，列为未对平。'));
  }
  const excluded = (books.excluded || []).map(item => `${item.record}·${item.reason}`).join('；');
  if (excluded) target.append(element('div', 'touch-key', `未参与：${excluded}`));
}
