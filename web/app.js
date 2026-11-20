const API = '';
let token = localStorage.getItem('m68tok') || 'change-me';
const $ = s => document.querySelector(s);
$('#tok').value = token;
$('#tok').onchange = e => { token = e.target.value; localStorage.setItem('m68tok', token); loadAll(); };

async function api(path, opt = {}) {
  const r = await fetch(API + path, { ...opt,
    headers: { 'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/json', ...(opt.headers||{}) }});
  if (!r.ok) throw new Error(r.status + ' ' + await r.text());
  return r.json();
}

/* ---------- map ---------- */
const map = L.map('map', { doubleClickZoom: false }).setView([39.9, 116.4], 11);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  { maxZoom: 19, attribution: '© OSM' }).addTo(map);
const markers = {};          // terminal_id -> marker
let devLayer = L.layerGroup().addTo(map);
let fenceLayer = L.layerGroup().addTo(map);
let trackLine = null, trackTid = null;

function icon(d) {
  const c = !d.online ? '#ff5c5c' : (d.external_power ? '#34c77b' : '#ffb020');
  return L.divIcon({ className:'', iconSize:[14,14],
    html:`<div style="width:12px;height:12px;border-radius:50%;background:${c};
          border:2px solid #fff;box-shadow:0 0 4px #000"></div>` });
}

function srcBadge(s){ return {gnss:'GNSS',lbs:'基站',last:'最后有效'}[s]||s||'-'; }

/* ---------- state ---------- */
let devices = [], alarms = [], fences = [], overview = {}, tab = 'dev';

async function loadAll() {
  try {
    [overview, devices, fences] = await Promise.all([
      api('/api/overview'), api('/api/overview/map'), api('/api/fences')]);
    alarms = await api('/api/alarms?active=true');
    renderStats(); renderPane(); renderMap();
    // detail 面板打开时跟随刷新
    if (_detailTid) {
      const d = devices.find(x => x.terminal_id === _detailTid);
      if (d) showDetail(d); else { _detailTid = null; $('#detail').style.display='none'; }
    }
  } catch (e) { console.error(e); }
}

function renderStats() {
  $('#s-total').textContent = overview.total ?? '-';
  $('#s-online').textContent = overview.online ?? '-';
  $('#s-batt').textContent = overview.on_battery ?? '-';
  $('#s-alarm').textContent = overview.active_alarms ?? '-';
}

function renderMap() {
  devLayer.clearLayers(); fenceLayer.clearLayers();
  // 轨迹图层独立保留,loadAll 不清它
  for (const d of devices) {
    if (d.lat == null) continue;
    const m = L.marker([d.lat, d.lng], { icon: icon(d) });
    m.on('click', () => showDetail(d));
    m.bindTooltip(`${d.asset_no||d.terminal_id} · ${srcBadge(d.loc_source)}`);
    m.addTo(devLayer); markers[d.terminal_id] = m;
  }
  for (const f of fences) {
    if (!f.enabled) continue;
    if (f.shape_type === 'circle' && f.center_lat != null)
      L.circle([f.center_lat, f.center_lng],
        {radius:f.radius_m||0, color:'#3ba1ff', weight:1, dashArray:'4'}).addTo(fenceLayer)
        .bindTooltip(f.name);
    else if (f.shape_type === 'polygon' && f.polygon)
      L.polygon(JSON.parse(f.polygon)[0].map(p=>[p[1],p[0]]),
        {color:'#3ba1ff', weight:1, dashArray:'4'}).addTo(fenceLayer)
        .bindTooltip(f.name);
  }
}

function renderPane() {
  const p = $('#pane');
  if (tab === 'dev') {
    p.innerHTML = devices.map(d => `
      <div class="card" onclick="showDetail(devices.find(x=>x.terminal_id==='${d.terminal_id}'))">
        <div class="t"><b>${d.asset_no||d.terminal_id}</b>
          <span class="badge ${d.online?'b-on':'b-off'}">${d.online?'在线':'离线'}</span></div>
        <div class="mut">${d.brand||''} ${d.model||''} · ${srcBadge(d.loc_source)}
          ${d.battery_pct!=null?` · ⚡${d.battery_pct}%`:''}
          ${!d.external_power?' · <span class="badge b-batt">电池</span>':''}</div>
      </div>`).join('') || '<div class="mut">无设备</div>';
  } else if (tab === 'alm') {
    p.innerHTML = alarms.map(a => `
      <div class="card alm ${a.level==='critical'?'crit':(a.level==='info'?'info':'')}">
        <div class="t"><b>${a.type}</b><span class="mut">${a.terminal_id}</span></div>
        <div class="mut">${a.detail||''} · ${new Date(a.triggered_at).toLocaleString()}</div>
        <div class="btnrow">
          <button class="btn sec" onclick="ack(${a.id},event)">认领</button>
          <button class="btn sec" onclick="closeAlarm(${a.id},event)">关闭</button>
        </div>
      </div>`).join('') || '<div class="mut">无活动告警</div>';
  } else {
    p.innerHTML = fences.map(f => `
      <div class="card fence-item">
        <div>
          <div class="t"><b>${f.name}</b>
            <span class="badge ${f.enabled?'b-on':'b-off'}">${f.enabled?'启用':'停用'}</span></div>
          <div class="mut">${f.site||'-'} · ${f.shape_type} · r=${Math.round(f.radius_m||0)}m · 缓冲${f.buffer_m}m</div>
          <div class="tagrow">${(f.devices&&f.devices.length)
            ? f.devices.map(d=>`<span class="tag">${d}</span>`).join('')
            : '<span class="tag">全部设备</span>'}
            ${f.alert_on_enter?'<span class="tag">进入</span>':''}
            ${f.alert_on_leave?'<span class="tag">离开</span>':''}</div>
        </div>
        <div class="acts">
          <button class="btn sec" onclick="editFence(${f.id},event)">编辑</button>
          <button class="btn sec" onclick="toggleFence(${f.id},event)">${f.enabled?'停':'启'}</button>
          <button class="btn sec" onclick="delFence(${f.id},event)">删</button>
        </div>
      </div>`).join('') || '<div class="mut">无围栏，用右上按钮绘制</div>';
  }
}

let _detailTid = null;             // detail 面板当前显示的设备
async function showDetail(d) {
  const el = $('#detail');
  if (!d) { _detailTid = null; el.style.display='none'; return; }
  _detailTid = d.terminal_id;
  el.style.display = 'block';
  el.innerHTML = `<h2>${d.asset_no||d.terminal_id}</h2>
    ${[['终端', d.terminal_id],['在线', d.online?'是':'否'],
       ['位置', d.lat?`${d.lat.toFixed(5)}, ${d.lng.toFixed(5)}`:'未知'],
       ['来源', srcBadge(d.loc_source)+' · '+(d.located?'有效':'无效/过期')],
       ['定位时间', d.located_at?new Date(d.located_at).toLocaleString():'-'],
       ['通信时间', d.last_comm_at?new Date(d.last_comm_at).toLocaleString():'-'],
       ['电量', d.battery_pct!=null?d.battery_pct+'%':'-'],
       ['供电', d.external_power?'外部':'电池'],
       ['电压', d.ext_voltage_mv!=null?(d.ext_voltage_mv/1000).toFixed(2)+'V':'-'],
       ['ACC', d.acc_on?'开':'关'],
       ['模式', d.work_mode!=null?d.work_mode:'-'],
       ['间隔', d.report_interval!=null?d.report_interval+'s':'-'],
       ['ICCID', d.iccid||'-'],['IMEI', d.imei||'-'],
       ['串号', d.product_id||'-']]
      .map(kv=>`<div class="kv"><span>${kv[0]}</span><span>${kv[1]}</span></div>`).join('')}
    <div class="btnrow">
      <button class="btn" onclick="track('${d.terminal_id}')">轨迹</button>
      <button class="btn sec" onclick="clearTrack()">清除</button>
      <button class="btn sec" onclick="cmd('${d.terminal_id}','locate')">点名</button>
      <button class="btn sec" onclick="cmd('${d.terminal_id}','reset')">复位</button>
      <button class="btn sec" onclick="setInt('${d.terminal_id}')">上报间隔</button>
    </div>`;
  if (d.lat) map.panTo([d.lat, d.lng]);
}

async function track(tid) {
  try {
    const pts = await api(`/api/locations/${tid}/history?last=600`);
    clearTrack();
    // lat/lng 有值就画 —— LBS/WiFi 定位 (located=false) 也是有效轨迹点
    const good = pts.filter(p => p.lat != null && p.lng != null);
    if (!good.length) { alert('该设备 24h 内无轨迹点'); return; }
    const step = Math.max(1, Math.floor(good.length / 400));
    const shown = good.filter((_, i) => i % step === 0);
    trackTid = tid;
    trackLine = L.featureGroup().addTo(map);   // featureGroup 才有 getBounds
    // 主线 + 每点一个小圆点(让稀疏段也可见)
    L.polyline(shown.map(p => [p.lat, p.lng]), {
      color:'#3ba1ff', weight:4, opacity:.9}).addTo(trackLine);
    shown.forEach((p, i) => {
      const isEnd = i === 0 || i === shown.length - 1;
      L.circleMarker([p.lat, p.lng], {
        radius: isEnd ? 7 : 3,
        color: i === 0 ? '#34c77b' : (isEnd ? '#ff5c5c' : '#3ba1ff'),
        weight: 2, fillOpacity: .9,
      }).addTo(trackLine)
        .bindTooltip(`${i===0?'起点':(isEnd?'最新':'#'+i)} ${new Date(p.collected_at).toLocaleTimeString()}<br>${p.lat.toFixed(5)},${p.lng.toFixed(5)}`);
    });
    map.fitBounds(trackLine.getBounds(), {padding:[40,40]});
    $('#drawhint').textContent = `轨迹:${tid}(${shown.length}/${good.length}点)`;
  } catch (e) { alert('拉轨迹失败: ' + e.message); }
}

function clearTrack() {
  if (trackLine) { map.removeLayer(trackLine); trackLine = null; trackTid = null; }
  $('#drawhint').textContent = '';
}

async function cmd(tid, c) {
  try { await api(`/api/commands/${tid}/${c}`, {method:'POST'});
        alert(c==='reset'?'复位已下发':'点名已下发'); }
  catch(e){ alert('失败: '+e.message); }
}
async function setInt(tid) {
  const s = prompt('上报间隔秒数:', '30'); if (!s) return;
  try { await api(`/api/commands/${tid}/params`,
    {method:'POST', body:JSON.stringify({params:{'0x0001':+s}})});
    alert('已下发'); } catch(e){ alert('失败: '+e.message); }
}
/* ---------- fence edit modal ---------- */
let editingFence = null;   // null=新建; id=编辑; 或 {geom} 暂存绘制形状

function openFenceModal(id, geom) {
  editingFence = id ? {id} : {geom};
  const f = id ? fences.find(x => x.id === id) : null;
  $('#fm-title').textContent = f ? '编辑围栏' : '新建围栏';
  $('#fm-name').value = f ? f.name : '';
  $('#fm-site').value = f ? (f.site||'') : '';
  $('#fm-buffer').value = f ? f.buffer_m : 50;
  $('#fm-enter').checked = f ? f.alert_on_enter : true;
  $('#fm-leave').checked = f ? f.alert_on_leave : true;
  const bound = f ? (f.devices||[]) : [];
  $('#fm-all').checked = bound.length === 0;
  renderDevList(bound);
  $('#fm-all').onchange = e => renderDevList(e.target.checked ? [] : bound);
  $('#fmodal').style.display = 'flex';
}
function renderDevList(checked) {
  const all = $('#fm-all').checked;
  $('#fm-devlist').innerHTML = all
    ? '<div class="mut">对所有设备生效</div>'
    : devices.map(d => `
      <div class="chk"><input type="checkbox" class="fmdev" value="${d.terminal_id}"
        ${checked.includes(d.terminal_id)?'checked':''}/>
        <span>${d.asset_no||d.terminal_id} <span class="mut">${d.terminal_id}</span></span>
      </div>`).join('') || '<div class="mut">暂无设备</div>';
}
function closeFenceModal() { $('#fmodal').style.display = 'none'; editingFence = null; }
$('#fm-cancel').onclick = closeFenceModal;

$('#fm-save').onclick = async () => {
  const name = $('#fm-name').value.trim();
  if (!name) { alert('名称必填'); return; }
  const payload = {
    name,
    site: $('#fm-site').value.trim(),
    buffer_m: parseFloat($('#fm-buffer').value) || 0,
    alert_on_enter: $('#fm-enter').checked,
    alert_on_leave: $('#fm-leave').checked,
    devices: $('#fm-all').checked ? []
      : [...document.querySelectorAll('.fmdev:checked')].map(c => c.value),
  };
  let url = '/api/fences', method = 'POST';
  if (editingFence.id) { url += '/' + editingFence.id; method = 'PUT'; }
  else Object.assign(payload, editingFence.geom);   // 新建: 补上几何
  try {
    await api(url, {method, body: JSON.stringify(payload)});
    closeFenceModal(); loadAll();
  } catch (e) { alert('保存失败: ' + e.message); }
};

async function editFence(id, ev) { ev.stopPropagation(); openFenceModal(id); }
async function toggleFence(id, ev) { ev.stopPropagation();
  await api(`/api/fences/${id}/toggle`, {method:'POST'}); loadAll(); }
async function delFence(id, ev) { ev.stopPropagation();
  if (confirm('删除该围栏?')) { await api(`/api/fences/${id}`, {method:'DELETE'}); loadAll(); } }

async function ack(id, ev){
  ev.stopPropagation();
  try {
    await api(`/api/alarms/${id}/ack`,{method:'POST'});
    await loadAll();
  } catch(e) { alert('认领失败: ' + e.message); }
}
async function closeAlarm(id, ev){
  ev.stopPropagation();
  try {
    await api(`/api/alarms/${id}/close`,{method:'POST'});
    await loadAll();
  } catch(e) { alert('关闭失败: ' + e.message); }
}

/* ---------- fence drawing ---------- */
let drawMode = null, drawPts = [], drawTemp = null, circlePreview = null;

function resetDraw() {
  drawMode = null; drawPts = [];
  if (drawTemp) { map.removeLayer(drawTemp); drawTemp = null; }
  if (circlePreview) { map.removeLayer(circlePreview); circlePreview = null; }
  $('#drawhint').textContent = '';
}
function startDraw(mode) {
  resetDraw(); drawMode = mode;
  $('#drawhint').textContent = mode === 'circle'
    ? '① 点圆心 ② 再点边缘定半径 (Esc取消)'
    : '逐点点击顶点, 双击完成 (Esc取消)';
}
$('#b-circle').onclick = () => startDraw('circle');
$('#b-poly').onclick = () => startDraw('poly');
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { resetDraw(); clearTrack(); }
});

map.on('click', async e => {
  if (!drawMode) return;
  drawPts.push(e.latlng);
  if (drawMode === 'circle') {
    if (drawPts.length === 1) {
      circlePreview = L.circle(drawPts[0], {radius: 0,
        color: '#3ba1ff', weight: 1, dashArray: '4'}).addTo(map);
      $('#drawhint').textContent = '② 再点边缘定半径 (Esc取消)';
      return;
    }
    const r = map.distance(drawPts[0], drawPts[1]);
    const c = drawPts[0];
    resetDraw();
    openFenceModal(null, {shape_type: 'circle', center_lat: c.lat,
                          center_lng: c.lng, radius_m: r});
  } else {                                    // poly
    if (drawTemp) map.removeLayer(drawTemp);
    drawTemp = L.polyline(drawPts,
      {color: '#3ba1ff', weight: 2, dashArray: '4'}).addTo(map);
  }
});

map.on('mousemove', e => {                     // 圆形半径预览
  if (drawMode === 'circle' && circlePreview && drawPts.length === 1)
    circlePreview.setRadius(map.distance(drawPts[0], e.latlng));
});

map.on('dblclick', async () => {
  if (drawMode !== 'poly' || drawPts.length < 3) return;
  const pts = drawPts.slice();
  resetDraw();
  const ring = pts.map(p => [p.lng, p.lat]); ring.push(ring[0]);
  openFenceModal(null, {shape_type: 'polygon',
                        polygon: JSON.stringify([ring])});
});

/* ---------- tabs ---------- */
document.querySelectorAll('.tabs button').forEach(b =>
  b.onclick = () => { tab=b.dataset.tab;
    document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('on',x===b));
    renderPane(); });

loadAll();
setInterval(loadAll, 15000);
