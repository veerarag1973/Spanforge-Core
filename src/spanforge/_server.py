"""spanforge._server — Local trace viewer HTTP server + embedded SPA.

Provides a JSON API and a single-page trace viewer over stdlib ``http.server``
for browsing traces captured in the in-process
:class:`~spanforge._store.TraceStore`.  Launched via ``spanforge ui``
(opens browser) or ``spanforge serve`` (API only).

API endpoints
-------------

==============================  =====================================
``GET /``                       Embedded SPA trace viewer (HTML)
``GET /health``                 Returns ``{"status": "ok"}``
``GET /ready``                  Readiness check — 200 if store and
                                exporter are accessible, 503 otherwise.
                                Returns ``{"ready": true, "checks": {...}}``
``GET /traces``                 Returns all trace IDs.
``GET /traces/{trace_id}``      Returns all events for a trace.
``GET /events``                 Returns the most recent 200 events
                                across all traces (newest first).
``GET /compliance/summary``     Returns compliance summary across all
                                loaded frameworks (SOC2, HIPAA, etc.)
``GET /compliance/events``      Returns events filtered by ``?type=``
                                query parameter.
``GET /metrics``                Basic plaintext counters.
==============================  =====================================

All responses are UTF-8 JSON.  CORS headers are **not** sent by default;
pass ``cors_origins="*"`` (or a specific origin) to enable cross-origin
access for a local HTML/JS viewer.

Usage
-----
::

    # Programmatic
    from spanforge._server import TraceViewerServer
    server = TraceViewerServer(port=8888)
    server.start()          # background daemon thread
    # ...
    server.stop()

    # CLI
    $ spanforge serve --port 8888
    $ spanforge serve --port 8888 --file my_spans.jsonl
"""

from __future__ import annotations

import http.server
import json
import logging
import re
import threading
import urllib.parse
from typing import Any

__all__ = [
    "TraceViewerServer",
]

_log = logging.getLogger("spanforge.server")

_TRACE_ID_PATH_RE = re.compile(r"^/traces/([0-9a-f]{32})$")
_MAX_EVENTS_PER_LIST = 200

# ---------------------------------------------------------------------------
# Embedded SPA — single-file trace viewer (vanilla JS, zero external deps)
# ---------------------------------------------------------------------------

_VIEWER_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>spanforge — Trace Viewer</title>
<style>
:root{--bg:#0f1117;--bg-panel:#1a1d27;--bg-hover:#242736;--border:#2a2d3a;--text:#e2e8f0;--text-muted:#94a3b8;--accent:#7c3aed;--accent-light:#a78bfa;--success:#10b981;--warning:#f59e0b;--error:#ef4444;--radius:6px;--font:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;--mono:'JetBrains Mono','Fira Code','Cascadia Code',monospace}
[data-theme=light]{--bg:#f8fafc;--bg-panel:#ffffff;--bg-hover:#f1f5f9;--border:#e2e8f0;--text:#1e293b;--text-muted:#64748b}
*{box-sizing:border-box;margin:0;padding:0}html,body{height:100%;overflow:hidden}
body{font-family:var(--font);background:var(--bg);color:var(--text);display:flex;flex-direction:column;font-size:13px}
#header{display:flex;align-items:center;gap:10px;padding:0 16px;height:50px;background:var(--bg-panel);border-bottom:1px solid var(--border);flex-shrink:0}
.logo{font-size:15px;font-weight:700;color:var(--accent-light);letter-spacing:-0.5px;white-space:nowrap}
.stat-chip{padding:3px 9px;border-radius:20px;background:var(--bg-hover);color:var(--text-muted);font-size:11px;white-space:nowrap}
.chain-ok{color:var(--success)}.chain-warn{color:var(--warning)}.chain-none{color:var(--text-muted)}
#filter-input{margin-left:auto;padding:5px 10px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg);color:var(--text);font-size:12px;width:200px;outline:none}
#filter-input:focus{border-color:var(--accent)}
.icon-btn{cursor:pointer;padding:5px 8px;border-radius:var(--radius);background:none;border:none;color:var(--text-muted);font-size:14px;transition:background 0.15s}
.icon-btn:hover{background:var(--bg-hover);color:var(--text)}
#main{display:flex;flex:1;overflow:hidden}
/* Left panel */
#traces-panel{width:220px;flex-shrink:0;border-right:1px solid var(--border);overflow-y:auto;display:flex;flex-direction:column}
.panel-title{padding:9px 12px 6px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.8px;color:var(--text-muted);position:sticky;top:0;background:var(--bg-panel);border-bottom:1px solid var(--border)}
.trace-item{padding:9px 12px;cursor:pointer;border-bottom:1px solid var(--border);transition:background .1s}
.trace-item:hover{background:var(--bg-hover)}
.trace-item.active{background:var(--bg-hover);border-left:3px solid var(--accent);padding-left:9px}
.trace-id{font-family:var(--mono);font-size:11px;color:var(--accent-light)}
.trace-meta{margin-top:3px;display:flex;align-items:center;gap:5px;color:var(--text-muted);font-size:10px}
.badge{padding:1px 5px;border-radius:3px;font-size:10px;font-weight:600}
.badge-ok{background:rgba(16,185,129,.15);color:#10b981}.badge-err{background:rgba(239,68,68,.15);color:#ef4444}
.badge-n{background:var(--border);color:var(--text-muted)}
/* Center panel */
#center-panel{flex:1;overflow-y:auto;display:flex;flex-direction:column}
.event-row{display:flex;align-items:center;gap:8px;padding:8px 16px;border-bottom:1px solid var(--border);cursor:pointer;transition:background .1s}
.event-row:hover{background:var(--bg-hover)}.event-row.active{background:var(--bg-hover);border-left:3px solid var(--accent);padding-left:13px}
.evt-type{padding:2px 6px;border-radius:4px;font-size:10px;font-weight:600;white-space:nowrap;font-family:var(--mono)}
.evt-id{font-family:var(--mono);font-size:10px;color:var(--text-muted);min-width:100px}
.evt-source{color:var(--text-muted);font-size:11px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.evt-ts{font-size:10px;color:var(--text-muted);white-space:nowrap}
/* Waterfall */
#wf-header{padding:8px 16px;background:var(--bg-panel);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px;flex-shrink:0;position:sticky;top:0;z-index:1}
.wf-back{cursor:pointer;color:var(--accent-light);font-size:11px;text-decoration:none}.wf-back:hover{text-decoration:underline}
.wf-tid{font-family:var(--mono);font-size:10px}.wf-cost{color:var(--success);font-size:11px;margin-left:auto}.wf-dur{color:var(--text-muted);font-size:11px}
.wf-body{padding:6px 16px 16px}
.wf-ruler{display:flex;padding:0 0 4px 196px;font-size:9px;color:var(--text-muted);margin-bottom:2px}
.wf-ruler-mark{flex:1}
.wf-row{display:flex;align-items:center;gap:8px;padding:4px;border-radius:var(--radius);cursor:pointer;transition:background .1s}
.wf-row:hover{background:var(--bg-hover)}.wf-row.active{background:var(--bg-hover)}
.wf-label{width:188px;flex-shrink:0;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:flex;align-items:center;gap:4px}
.wf-timeline{flex:1;height:20px;position:relative;background:var(--bg-hover);border-radius:3px}
.wf-bar{position:absolute;top:2px;height:16px;border-radius:3px;min-width:3px}.wf-bar:hover{opacity:.8}
.wf-dl{width:56px;flex-shrink:0;font-size:10px;color:var(--text-muted);text-align:right}
/* Detail panel */
#detail-panel{width:340px;flex-shrink:0;border-left:1px solid var(--border);overflow-y:auto}
.det-hdr{padding:10px 12px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg-panel)}
.det-type{margin-bottom:6px}.det-kv{display:flex;flex-direction:column;gap:3px}
.kv-row{display:flex;gap:8px;font-size:11px}.kv-k{color:var(--text-muted);min-width:72px;flex-shrink:0}.kv-v{font-family:var(--mono);font-size:10px;word-break:break-all}
.det-sec{padding:9px 12px;border-bottom:1px solid var(--border)}
.sec-title{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;color:var(--text-muted);margin-bottom:7px}
.json-view{font-family:var(--mono);font-size:11px;line-height:1.6;white-space:pre-wrap;word-break:break-all}
.jk{color:#7dd3fc}.js{color:#86efac}.jn{color:#fca5a5}.jb{color:#fbbf24}.jl{color:#94a3b8}
.sig-badge{display:inline-flex;align-items:center;gap:4px;padding:2px 7px;border-radius:10px;font-size:10px;font-weight:600}
.sig-yes{background:rgba(16,185,129,.15);color:#10b981}.sig-no{background:rgba(148,163,184,.15);color:#94a3b8}
/* Empty states */
.empty{display:flex;flex-direction:column;align-items:center;justify-content:center;flex:1;gap:8px;color:var(--text-muted);padding:48px}
.empty-icon{font-size:32px}
/* Scrollbar */
::-webkit-scrollbar{width:5px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
@keyframes spin{to{transform:rotate(360deg)}}
/* Compliance dashboard */
.comp-dash{padding:20px;overflow-y:auto;flex:1}
.comp-card{background:var(--bg-panel);border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:14px}
.comp-card-title{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;color:var(--text-muted);margin-bottom:10px}
.comp-chain-status{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600}
.comp-chain-ok{color:var(--success)}.comp-chain-err{color:var(--error)}.comp-chain-warn{color:var(--warning)}
.comp-fw-hdr{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.comp-fw-name{font-size:13px;font-weight:700;color:var(--text)}
.comp-fw-pct{font-size:12px;font-weight:600;padding:2px 8px;border-radius:10px}
.comp-clause-row{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--border);font-size:12px}
.comp-clause-row:last-child{border-bottom:none}
.comp-clause-id{font-family:var(--mono);font-size:10px;color:var(--accent-light);min-width:80px}
.comp-clause-desc{flex:1;color:var(--text)}
.comp-clause-badge{padding:2px 7px;border-radius:3px;font-size:10px;font-weight:600}
.comp-pass{background:rgba(16,185,129,.15);color:#10b981}.comp-fail{background:rgba(239,68,68,.15);color:#ef4444}
.comp-stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}
.comp-stat{text-align:center;padding:10px;background:var(--bg-hover);border-radius:var(--radius)}
.comp-stat-val{font-size:20px;font-weight:700}.comp-stat-lbl{font-size:10px;color:var(--text-muted);margin-top:2px}
.comp-back{cursor:pointer;color:var(--accent-light);font-size:12px;background:none;border:none;padding:4px 0;margin-bottom:12px;font-family:var(--font)}
.comp-back:hover{text-decoration:underline}
.comp-model-row{display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);font-size:12px}
.comp-model-row:last-child{border-bottom:none}
.comp-model-name{font-family:var(--mono);font-size:11px;color:var(--accent-light);min-width:140px}
.comp-model-meta{color:var(--text-muted);font-size:11px}
</style></head>
<body>
<header id="header">
  <div class="logo">&#x2B21; spanforge</div>
  <div class="stat-chip" id="s-traces">— traces</div>
  <div class="stat-chip" id="s-events">— events</div>
  <div class="stat-chip" id="s-cost">$—</div>
  <div class="stat-chip" id="s-chain">chain</div>
  <div class="stat-chip" id="s-compliance" title="Click to view compliance dashboard" style="cursor:pointer">compliance</div>
  <input id="filter-input" type="text" placeholder="Filter traces, events, IDs…" oninput="applyFilter()">
  <button class="icon-btn" id="theme-btn" title="Toggle light/dark" onclick="toggleTheme()">&#9728;</button>
  <button class="icon-btn" title="Refresh" onclick="loadData()">&#8635;</button>
  <button class="icon-btn" title="Export as JSONL" onclick="exportEvents()">&#8659;</button>
</header>
<div id="main">
  <nav id="traces-panel">
    <div class="panel-title">Traces</div>
    <div id="traces-list"></div>
  </nav>
  <section id="center-panel"><div id="center-content"></div></section>
  <aside id="detail-panel"><div id="detail-content">
    <div class="empty"><div class="empty-icon">&#128269;</div><div>Select an event to inspect</div></div>
  </div></aside>
</div>
<script>
// ─── State ─────────────────────────────────────────────────────────────────
const S={events:[],traceMap:{},sortedTraces:[],selTrace:null,selEvent:null,filter:'',dark:true,compData:null,compView:false};

// ─── Colors ─────────────────────────────────────────────────────────────────
const TC={'llm.trace':'#3b82f6','llm.cost':'#10b981','llm.eval':'#8b5cf6','llm.guard':'#f59e0b',
  'llm.redact':'#ef4444','llm.audit':'#eab308','llm.cache':'#06b6d4','llm.drift':'#f97316'};
function tc(et){const ns=(et||'').split('.').slice(0,2).join('.');return TC[ns]||'#6b7280';}

// ─── Helpers ─────────────────────────────────────────────────────────────────
function fmtTime(ts){if(!ts)return'';try{const d=new Date(ts);return d.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});}catch{return ts;}}
function fmtDur(ms){if(ms>=1000)return(ms/1000).toFixed(2)+'s';if(ms>=1)return ms.toFixed(1)+'ms';return(ms*1000).toFixed(0)+'\\u00b5s';}
function shortType(et){return(et||'unknown').split('.').slice(-2).join('.');}
function matches(ev,f){if(!f)return true;f=f.toLowerCase();return[ev.event_type,ev.source,ev.event_id,ev.trace_id].some(x=>String(x||'').toLowerCase().includes(f));}
function costOf(ev){const p=ev.payload||{};return+(p.cost_usd||p.total_cost?.total_cost_usd||0);}
function startNs(ev){const p=ev.payload||{};return p.start_time_unix_nano?+p.start_time_unix_nano:new Date(ev.timestamp||0).getTime()*1e6;}
function endNs(ev){const p=ev.payload||{};if(p.end_time_unix_nano)return+p.end_time_unix_nano;if(p.duration_ms!=null)return startNs(ev)+p.duration_ms*1e6;return startNs(ev)+1e6;}
function durMs(ev){const p=ev.payload||{};return p.duration_ms!=null?+p.duration_ms:(endNs(ev)-startNs(ev))/1e6;}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}

// ─── Syntax highlight ───────────────────────────────────────────────────────
function synHi(obj){
  return JSON.stringify(obj,null,2).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/("(?:\\u[0-9a-fA-F]{4}|\\[^u]|[^\\\\"])*"(\\s*:)?|\\b(?:true|false|null)\\b|-?\\d+(?:\\.\\d*)?(?:[eE][+\\-]?\\d+)?)/g,m=>{
      let c='jn';if(/^"/.test(m)){c=/:$/.test(m)?'jk':'js';}else if(/true|false/.test(m))c='jb';else if(/null/.test(m))c='jl';
      return`<span class="${c}">${m}</span>`;});
}

// ─── Data loading ───────────────────────────────────────────────────────────
async function loadData(){
  try{
    const r=await fetch('/events?limit=2000');const d=await r.json();const evts=d.events||[];
    const tm={};let cost=0,signed=0;
    for(const e of evts){const tid=e.trace_id||'__none__';if(!tm[tid])tm[tid]=[];tm[tid].push(e);cost+=costOf(e);if(e.signature)signed++;}
    for(const a of Object.values(tm))a.sort((a,b)=>startNs(a)-startNs(b));
    const latest=arr=>arr.reduce((m,e)=>{const t=new Date(e.timestamp||0).getTime();return t>m?t:m;},0);
    const sorted=Object.keys(tm).sort((a,b)=>latest(tm[b])-latest(tm[a]));
    Object.assign(S,{events:evts,traceMap:tm,sortedTraces:sorted});
    renderHeader({traces:sorted.length,events:evts.length,cost,signed});
    renderTraceList();renderCenter();
    loadComplianceSummary();
  }catch(e){console.error('load failed',e);}
}

async function loadComplianceSummary(){
  try{
    const r=await fetch('/compliance/summary');const d=await r.json();
    S.compData=d;
    const el=document.getElementById('s-compliance');
    // GA-02-A: Show chain integrity + PII in compliance banner
    const chainOk=d.chain_valid;const pii=d.pii_hits||0;const tampered=d.chain_tampered||0;
    if(tampered>0){el.innerHTML=`<span style="color:var(--error)">&#10007; chain: TAMPERED (${tampered})</span>`;el.title='Chain integrity compromised! '+tampered+' tampered event(s)';}
    else if(!d.frameworks||!d.frameworks.length){el.innerHTML='<span class="chain-none">compliance: n/a</span>';}
    else{
      const avg=d.frameworks.reduce((s,f)=>s+f.pct,0)/d.frameworks.length;
      let extra=pii>0?` PII:${pii}`:'';
      if(avg>=90)el.innerHTML=`<span class="chain-ok">&#10003; compliance: ${Math.round(avg)}%${extra}</span>`;
      else if(avg>=50)el.innerHTML=`<span class="chain-warn">&#9888; compliance: ${Math.round(avg)}%${extra}</span>`;
      else el.innerHTML=`<span style="color:var(--error)">&#10007; compliance: ${Math.round(avg)}%${extra}</span>`;
    }
    el.onclick=()=>showComplianceDashboard();
  }catch(e){document.getElementById('s-compliance').innerHTML='<span class="chain-none">compliance: error</span>';}
}

function showComplianceDashboard(){
  S.compView=true;
  const el=document.getElementById('center-content');
  const d=S.compData;
  if(!d){el.innerHTML='<div class="empty"><div class="empty-icon">&#128203;</div><div>No compliance data</div></div>';return;}

  // Chain integrity card
  let chainHtml='';
  const tampered=d.chain_tampered||0;const gaps=d.chain_gaps||0;
  if(tampered>0)chainHtml=`<div class="comp-chain-status comp-chain-err">&#10007; Chain TAMPERED &mdash; ${tampered} tampered event(s), ${gaps} gap(s)</div>`;
  else if(d.chain_valid)chainHtml=`<div class="comp-chain-status comp-chain-ok">&#10003; Chain Integrity Verified &mdash; ${d.chain_event_count||0} signed events</div>`;
  else chainHtml=`<div class="comp-chain-status comp-chain-warn">&#9888; Chain Not Verified &mdash; ${d.chain_event_count||0}/${d.event_count||0} signed</div>`;

  // Stats summary
  const pii=d.pii_hits||0;const piiEvts=d.pii_events_with_hits||0;
  const explPct=d.explanation_coverage_pct!=null?d.explanation_coverage_pct+'%':'n/a';

  // Frameworks
  let fwHtml='';
  if(d.frameworks&&d.frameworks.length){
    for(const fw of d.frameworks){
      const pctColor=fw.pct>=90?'var(--success)':fw.pct>=50?'var(--warning)':'var(--error)';
      const clauses=fw.clauses||[];
      const passed=clauses.filter(c=>c.passed).length;
      fwHtml+=`<div class="comp-card">
        <div class="comp-fw-hdr">
          <span class="comp-fw-name">${esc(fw.framework)}</span>
          <span class="comp-fw-pct" style="background:${pctColor}22;color:${pctColor}">${fw.pct}% (${fw.score}/${fw.max_score})</span>
          <span style="font-size:11px;color:var(--text-muted)">${passed}/${clauses.length} clauses passed</span>
        </div>
        ${clauses.map(c=>`<div class="comp-clause-row">
          <span class="comp-clause-id">${esc(c.clause_id)}</span>
          <span class="comp-clause-desc">${esc(c.description)}</span>
          <span class="comp-clause-badge ${c.passed?'comp-pass':'comp-fail'}">${c.passed?'PASS':'FAIL'}</span>
        </div>`).join('')}
      </div>`;
    }
  }else{fwHtml='<div class="comp-card"><div class="comp-card-title">Frameworks</div><div style="color:var(--text-muted);font-size:12px">No compliance frameworks evaluated. Load events with compliance-relevant types (llm.audit, llm.guard, llm.redact).</div></div>';}

  // Model registry card — extract unique models from events
  let modelHtml='';
  const models=new Map();
  for(const ev of S.events){
    const p=ev.payload||{};
    const model=p.model||p.model_id||p.model_name||(p.model_info&&p.model_info.model_id);
    if(model&&typeof model==='string'){
      if(!models.has(model)){
        models.set(model,{count:0,source:new Set(),lastSeen:null});
      }
      const m=models.get(model);
      m.count++;
      if(ev.source)m.source.add(ev.source);
      if(ev.timestamp)m.lastSeen=ev.timestamp;
    }
  }
  if(models.size>0){
    const rows=[...models.entries()].sort((a,b)=>b[1].count-a[1].count);
    modelHtml=`<div class="comp-card"><div class="comp-card-title">Model Registry</div>
      ${rows.map(([name,info])=>`<div class="comp-model-row">
        <span class="comp-model-name">${esc(name)}</span>
        <span class="comp-model-meta">${info.count} event${info.count!==1?'s':''}</span>
        <span class="comp-model-meta">${[...info.source].join(', ')}</span>
        <span class="comp-model-meta" style="margin-left:auto">${fmtTime(info.lastSeen)}</span>
      </div>`).join('')}
    </div>`;
  }else{
    modelHtml='<div class="comp-card"><div class="comp-card-title">Model Registry</div><div style="color:var(--text-muted);font-size:12px">No models detected in event payloads.</div></div>';
  }

  el.innerHTML=`<div class="comp-dash">
    <button class="comp-back" onclick="hideComplianceDashboard()">&#8592; Back to Traces</button>
    <div class="comp-card"><div class="comp-card-title">Overview</div>
      ${chainHtml}
      <div class="comp-stat-grid" style="margin-top:12px">
        <div class="comp-stat"><div class="comp-stat-val">${d.event_count||0}</div><div class="comp-stat-lbl">Total Events</div></div>
        <div class="comp-stat"><div class="comp-stat-val">${d.chain_event_count||0}</div><div class="comp-stat-lbl">Signed Events</div></div>
        <div class="comp-stat"><div class="comp-stat-val" style="color:${pii>0?'var(--error)':'var(--success)'}">${pii}</div><div class="comp-stat-lbl">PII Hits</div></div>
        <div class="comp-stat"><div class="comp-stat-val">${piiEvts}</div><div class="comp-stat-lbl">Events with PII</div></div>
        <div class="comp-stat"><div class="comp-stat-val">${explPct}</div><div class="comp-stat-lbl">Explanation Coverage</div></div>
      </div>
    </div>
    ${fwHtml}
    ${modelHtml}
  </div>`;
}

function hideComplianceDashboard(){S.compView=false;renderCenter();}

// ─── Header ─────────────────────────────────────────────────────────────────
function renderHeader({traces,events,cost,signed}){
  document.getElementById('s-traces').textContent=`${traces} trace${traces!==1?'s':''}`;
  document.getElementById('s-events').textContent=`${events} event${events!==1?'s':''}`;
  document.getElementById('s-cost').textContent=`$${cost.toFixed(4)}`;
  const el=document.getElementById('s-chain');const pct=events>0?Math.round(signed/events*100):0;
  if(!signed)el.innerHTML='<span class="chain-none">chain: unsigned</span>';
  else if(pct===100)el.innerHTML='<span class="chain-ok">&#10003; chain: 100% signed</span>';
  else el.innerHTML=`<span class="chain-warn">&#9888; chain: ${pct}% signed</span>`;
}

// ─── Trace list ──────────────────────────────────────────────────────────────
function renderTraceList(){
  const el=document.getElementById('traces-list');
  const f=S.filter.toLowerCase();const ts=S.sortedTraces;
  if(!ts.length){el.innerHTML='<div class="empty"><div class="empty-icon">&#128235;</div><div>No traces yet</div><div style="font-size:11px;margin-top:4px">Instrument your code with spanforge and run it.</div></div>';return;}
  el.innerHTML=ts.filter(tid=>!f||(tm=>tm.some(e=>matches(e,f)))(S.traceMap[tid]||[])||(tid!=='__none__'&&tid.includes(f)))
    .map(tid=>{const evts=S.traceMap[tid]||[];const cost=evts.reduce((s,e)=>s+costOf(e),0);
      const hasErr=evts.some(e=>(e.payload||{}).status==='error');const ts2=evts[evts.length-1]?.timestamp;
      const disp=tid==='__none__'?'(ungrouped)':tid.substring(0,14)+'\\u2026';const active=S.selTrace===tid;
      return`<div class="trace-item${active?' active':''}" data-tid="${esc(tid)}" onclick="selTrace(this.dataset.tid)">
        <div class="trace-id">${esc(disp)}</div>
        <div class="trace-meta">
          <span class="badge ${hasErr?'badge-err':'badge-ok'}">${hasErr?'ERR':'OK'}</span>
          <span class="badge badge-n">${evts.length}</span>
          ${cost>0?`<span style="color:var(--success)">$${cost.toFixed(4)}</span>`:''}
          <span style="margin-left:auto">${fmtTime(ts2)}</span>
        </div></div>`;}).join('');
}

// ─── Center panel ────────────────────────────────────────────────────────────
function renderCenter(){const el=document.getElementById('center-content');if(S.compView)showComplianceDashboard();else if(S.selTrace)renderWaterfall(el);else renderEventList(el);}

function renderEventList(el){
  const f=S.filter.toLowerCase();const evts=S.events.filter(e=>matches(e,f));
  if(!evts.length){el.innerHTML='<div class="empty"><div class="empty-icon">&#128203;</div><div>Select a trace from the left panel</div><div style="font-size:11px;margin-top:4px">Events will appear here once loaded.</div></div>';return;}
  el.innerHTML=`<div class="panel-title" style="padding:9px 16px 6px;position:sticky;top:0;background:var(--bg-panel)">All Events — newest first</div>`
    +evts.slice(0,500).map(ev=>{const c=tc(ev.event_type);const act=S.selEvent?.event_id===ev.event_id;
      return`<div class="event-row${act?' active':''}" data-eid="${esc(ev.event_id)}" onclick="selEvt(this.dataset.eid)">
        <span class="evt-type" style="background:${c}22;color:${c}">${esc(shortType(ev.event_type))}</span>
        <span class="evt-id">${esc((ev.event_id||'').substring(0,14))}</span>
        <span class="evt-source">${esc(ev.source||'')}</span>
        <span class="evt-ts">${fmtTime(ev.timestamp)}</span></div>`;}).join('');
}

function renderWaterfall(el){
  const tid=S.selTrace;const evts=S.traceMap[tid]||[];if(!evts.length)return;
  const f=S.filter.toLowerCase();const filtered=evts.filter(e=>matches(e,f));
  const minNs=Math.min(...evts.map(startNs));const maxNs=Math.max(...evts.map(endNs));
  const totalMs=(maxNs-minNs)/1e6||1;const cost=evts.reduce((s,e)=>s+costOf(e),0);
  const dispTid=tid==='__none__'?'(ungrouped)':tid;
  const marks=[0,.25,.5,.75,1].map(f=>`<span class="wf-ruler-mark">${(totalMs*f).toFixed(1)}ms</span>`).join('');
  el.innerHTML=`<div id="wf-header">
      <span class="wf-back" onclick="selTrace(null)">&#8592; All Traces</span>
      <span class="wf-tid" title="${esc(dispTid)}">${esc(dispTid.substring(0,36))}${dispTid.length>36?'\\u2026':''}</span>
      ${cost>0?`<span class="wf-cost">$${cost.toFixed(4)}</span>`:''}
      <span class="wf-dur">${totalMs.toFixed(2)}ms total</span>
    </div>
    <div class="wf-body">
      <div class="wf-ruler" style="padding-left:196px">${marks}</div>
      ${filtered.map(ev=>{const c=tc(ev.event_type);const sMs=(startNs(ev)-minNs)/1e6;const dMs=durMs(ev);
        const left=(sMs/totalMs*100).toFixed(2);const width=Math.max(.3,(dMs/totalMs*100)).toFixed(2);
        const name=(ev.payload||{}).span_name||shortType(ev.event_type);const act=S.selEvent?.event_id===ev.event_id;
        return`<div class="wf-row${act?' active':''}" data-eid="${esc(ev.event_id)}" onclick="selEvt(this.dataset.eid)">
          <div class="wf-label">
            <span class="evt-type" style="background:${c}22;color:${c};font-size:9px;padding:1px 4px">${esc(shortType(ev.event_type))}</span>
            <span style="overflow:hidden;text-overflow:ellipsis" title="${esc(name)}">${esc(name)}</span>
          </div>
          <div class="wf-timeline">
            <div class="wf-bar" style="left:${left}%;width:${width}%;background:${c}cc" title="${esc(ev.event_type)} ${dMs.toFixed(3)}ms"></div>
          </div>
          <div class="wf-dl">${fmtDur(dMs)}</div></div>`;}).join('')}
    </div>`;
}

// ─── Detail panel ────────────────────────────────────────────────────────────
function renderDetail(ev){
  const el=document.getElementById('detail-content');
  if(!ev){el.innerHTML='<div class="empty"><div class="empty-icon">&#128269;</div><div>Select an event to inspect</div></div>';return;}
  const c=tc(ev.event_type);const isSig=!!ev.signature;
  const kv=(k,v)=>`<div class="kv-row"><span class="kv-k">${k}</span><span class="kv-v">${esc(v||'—')}</span></div>`;
  const tags=ev.tags&&Object.keys(ev.tags).length?`<div class="det-sec"><div class="sec-title">Tags</div><div style="display:flex;flex-wrap:wrap;gap:4px">${Object.entries(ev.tags).map(([k,v])=>`<span style="padding:2px 6px;border-radius:3px;background:var(--border);font-size:10px;font-family:var(--mono)">${esc(k)}: ${esc(v)}</span>`).join('')}</div></div>`:'';
  el.innerHTML=`<div class="det-hdr">
      <div class="det-type">
        <span class="evt-type" style="background:${c}22;color:${c};font-size:12px">${esc(ev.event_type||'unknown')}</span>
        &nbsp;<span class="sig-badge ${isSig?'sig-yes':'sig-no'}">${isSig?'&#10003; Signed':'Unsigned'}</span>
      </div>
      <div class="det-kv" style="margin-top:8px">
        ${kv('event_id',(ev.event_id||'').substring(0,20)+'\\u2026')}
        ${kv('source',ev.source)}${kv('timestamp',ev.timestamp)}
        ${kv('trace_id',(ev.trace_id||'').substring(0,16)+(ev.trace_id?'\\u2026':''))}
        ${kv('span_id',ev.span_id)}${kv('schema',ev.schema_version)}
      </div></div>
    ${tags}
    <div class="det-sec"><div class="sec-title">Payload</div><div class="json-view">${synHi(ev.payload||{})}</div></div>
    ${isSig?`<div class="det-sec"><div class="sec-title">Chain</div><div class="det-kv">
      ${kv('checksum',(ev.checksum||'').substring(0,30)+'\\u2026')}
      ${kv('signature',(ev.signature||'').substring(0,30)+'\\u2026')}
      ${kv('prev_id',ev.prev_id)}</div></div>`:''}`;
}

// ─── Actions ─────────────────────────────────────────────────────────────────
function selTrace(tid){S.selTrace=tid;S.selEvent=null;renderTraceList();renderCenter();renderDetail(null);}
function selEvt(id){const ev=S.events.find(e=>e.event_id===id);S.selEvent=ev||null;renderDetail(ev);renderCenter();}
function applyFilter(){S.filter=document.getElementById('filter-input').value;renderTraceList();renderCenter();}
function toggleTheme(){S.dark=!S.dark;document.documentElement.setAttribute('data-theme',S.dark?'dark':'light');document.getElementById('theme-btn').textContent=S.dark?'\\u2600':'\\uD83C\\uDF19';}
function exportEvents(){const lines=S.events.map(e=>JSON.stringify(e)).join('\\n');const b=new Blob([lines],{type:'application/x-ndjson'});const u=URL.createObjectURL(b);const a=document.createElement('a');a.href=u;a.download='spanforge-traces.jsonl';a.click();URL.revokeObjectURL(u);}

// ─── Boot ─────────────────────────────────────────────────────────────────────
loadData();setInterval(loadData,30000);
</script>
</body></html>"""




class _TraceAPIHandler(http.server.BaseHTTPRequestHandler):
    # Injected by TraceViewerServer before binding.
    _get_store: Any  # callable: () -> TraceStore
    _cors_origins: str = ""  # configurable CORS origin; empty = no CORS header

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/":
            self._html_response(_VIEWER_HTML)
            return

        if path == "/health":
            self._json_response({"status": "ok"})

        elif path == "/api/stats":
            self._handle_api_stats()

        elif path == "/ready":
            self._handle_ready()

        elif path == "/traces":
            self._handle_list_traces()

        elif _TRACE_ID_PATH_RE.match(path):
            m = _TRACE_ID_PATH_RE.match(path)
            self._handle_get_trace(m.group(1))  # type: ignore[union-attr]

        elif path == "/events":
            self._handle_list_events()

        elif path == "/metrics":
            self._handle_metrics()

        elif path == "/compliance/summary":
            self._handle_compliance_summary()

        elif path == "/compliance/events":
            self._handle_compliance_events()

        else:
            self._error(404, "Not Found")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _handle_api_stats(self) -> None:
        """Return aggregated stats in JSON (for the SPA header chips)."""
        try:
            store = self._get_store()
            with store._lock:
                events = [e for evts in store._traces.values() for e in evts]
                trace_count = len(store._traces)
            cost = sum(
                float(e.payload.get("cost_usd") or e.payload.get("total_cost", {}).get("total_cost_usd") or 0)
                for e in events
            )
            signed = sum(1 for e in events if getattr(e, "signature", None))
            self._json_response({
                "traces": trace_count,
                "events": len(events),
                "total_cost_usd": cost,
                "signed_count": signed,
                "unsigned_count": len(events) - signed,
            })
        except Exception:  # NOSONAR
            _log.exception("api_stats error")
            self._error(500, "Internal Server Error")

    def _handle_list_traces(self) -> None:
        try:
            store = self._get_store()
            with store._lock:
                trace_ids = list(store._traces.keys())
            self._json_response({"trace_ids": trace_ids, "count": len(trace_ids)})
        except Exception:  # NOSONAR
            _log.exception("list_traces error")
            self._error(500, "Internal Server Error")

    def _handle_ready(self) -> None:
        """Return readiness status — 200 if the store is accessible, 503 otherwise."""
        import time as _time  # noqa: PLC0415

        checks: dict[str, str] = {}
        ready = True
        try:
            store = self._get_store()
            with store._lock:
                _ = len(store._traces)
            checks["store"] = "ok"
        except Exception as exc:  # NOSONAR
            checks["store"] = f"error: {exc}"
            ready = False

        try:
            from spanforge.config import get_config  # noqa: PLC0415
            cfg = get_config()
            checks["exporter"] = cfg.exporter
        except Exception as exc:  # NOSONAR
            checks["exporter"] = f"error: {exc}"
            ready = False

        payload = {
            "ready": ready,
            "checks": checks,
            "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
        }
        self._json_response(payload, status=200 if ready else 503)

    def _handle_get_trace(self, trace_id: str) -> None:
        try:
            store = self._get_store()
            events = store.get_trace(trace_id)
            if events is None:
                self._error(404, f"Trace {trace_id!r} not found")
                return
            self._json_response({
                "trace_id": trace_id,
                "event_count": len(events),
                "events": [_serialise_event(e) for e in events],
            })
        except Exception:  # NOSONAR
            _log.exception("get_trace error")
            self._error(500, "Internal Server Error")

    def _handle_list_events(self) -> None:
        try:
            parsed_url = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed_url.query)
            try:
                offset = max(0, int(params.get("offset", ["0"])[0]))
            except (ValueError, TypeError):
                offset = 0
            try:
                limit = min(
                    max(1, int(params.get("limit", [str(_MAX_EVENTS_PER_LIST)])[0])),
                    _MAX_EVENTS_PER_LIST,
                )
            except (ValueError, TypeError):
                limit = _MAX_EVENTS_PER_LIST

            store = self._get_store()
            all_events: list[Any] = []
            with store._lock:
                for evts in store._traces.values():
                    all_events.extend(evts)
            # Newest first.
            all_events.sort(
                key=lambda e: getattr(e, "timestamp", 0),
                reverse=True,
            )
            subset = all_events[offset:offset + limit]
            self._json_response({
                "event_count": len(subset),
                "total": len(all_events),
                "offset": offset,
                "limit": limit,
                "events": [_serialise_event(e) for e in subset],
            })
        except Exception:  # NOSONAR
            _log.exception("list_events error")
            self._error(500, "Internal Server Error")

    def _handle_metrics(self) -> None:
        try:
            from spanforge._stream import _export_error_count  # noqa: PLC0415
            store = self._get_store()
            with store._lock:
                trace_count = len(store._traces)
                event_count = sum(len(v) for v in store._traces.values())
            body = (
                f"spanforge_traces_in_store {trace_count}\n"
                f"spanforge_events_in_store {event_count}\n"
                f"spanforge_export_errors_total {_export_error_count}\n"
            )
            self._text_response(body)
        except Exception:  # NOSONAR
            _log.exception("metrics error")
            self._error(500, "Internal Server Error")

    def _handle_compliance_summary(self) -> None:
        """``GET /compliance/summary`` — aggregate compliance posture.

        GA-02-A: Returns chain integrity status, PII scan summary, and
        framework compliance scores.
        """
        try:
            from spanforge.core.compliance_mapping import ComplianceMappingEngine  # noqa: PLC0415
            from spanforge.redact import scan_payload  # noqa: PLC0415

            store = self._get_store()
            all_events: list[Any] = []
            with store._lock:
                for evts in store._traces.values():
                    all_events.extend(evts)

            # Chain integrity check
            chain_valid = False
            chain_tampered = 0
            chain_gaps = 0
            signed_count = sum(1 for e in all_events if getattr(e, "signature", None))
            try:
                import os as _os  # noqa: PLC0415
                org_secret = _os.environ.get("SPANFORGE_SIGNING_KEY", "")
                if org_secret and all_events:
                    from spanforge.signing import verify_chain as _vc  # noqa: PLC0415
                    chain_result = _vc(all_events, org_secret)
                    chain_valid = chain_result.valid
                    chain_tampered = chain_result.tampered_count
                    chain_gaps = len(chain_result.gaps)
            except Exception:  # noqa: BLE001
                pass

            # PII scan summary
            pii_hits_total = 0
            pii_events_with_hits = 0
            for e in all_events:
                payload = getattr(e, "payload", None)
                if isinstance(payload, dict):
                    result = scan_payload(payload)
                    if not result.clean:
                        pii_hits_total += len(result.hits)
                        pii_events_with_hits += 1

            # Framework compliance
            mapper = ComplianceMappingEngine()
            comp_result = mapper.evaluate(all_events)
            frameworks: list[dict[str, Any]] = []
            for fw in comp_result.frameworks:
                clauses: list[dict[str, Any]] = []
                for c in fw.clauses:
                    clauses.append({
                        "clause_id": c.clause_id,
                        "description": c.description,
                        "passed": c.passed,
                        "evidence_count": c.evidence_count,
                        "required_event_types": c.required_event_types,
                    })
                frameworks.append({
                    "framework": fw.framework,
                    "score": fw.score,
                    "max_score": fw.max_score,
                    "pct": round(fw.score / fw.max_score * 100, 1) if fw.max_score else 0,
                    "clauses": clauses,
                })
            self._json_response({
                "event_count": len(all_events),
                "chain_valid": chain_valid,
                "chain_event_count": signed_count,
                "chain_tampered": chain_tampered,
                "chain_gaps": chain_gaps,
                "pii_hits": pii_hits_total,
                "pii_events_with_hits": pii_events_with_hits,
                "frameworks": frameworks,
                "explanation_coverage_pct": self._compute_explanation_coverage_pct(all_events),
            })
        except Exception:  # NOSONAR
            _log.exception("compliance_summary error")
            self._error(500, "Internal Server Error")

    @staticmethod
    def _compute_explanation_coverage_pct(all_events: list[Any]) -> float | None:
        """Return the % of trace/HITL decisions that have a matching explanation event."""
        decision_count = sum(
            1 for e in all_events
            if str(getattr(e, "event_type", "")).startswith(("llm.trace.", "hitl."))
        )
        explanation_count = sum(
            1 for e in all_events
            if str(getattr(e, "event_type", "")).startswith("explanation.")
        )
        if decision_count > 0:
            return round(min(explanation_count / decision_count * 100, 100.0), 1)
        return None

    def _handle_compliance_events(self) -> None:
        """``GET /compliance/events?type=<prefix>&offset=N&limit=N`` — filter events by namespace prefix.

        GA-02-B: Uses namespace prefix matching (e.g. ``llm.audit`` matches
        ``llm.audit.chain.verified``), adds ``hmac_valid`` per event, and
        supports standard pagination via ``offset`` and ``limit``.
        Omitting ``type`` returns all compliance-relevant events (``llm.audit``,
        ``llm.guard``, ``llm.redact``, ``llm.compliance``).
        """
        try:
            import os as _os  # noqa: PLC0415
            from spanforge.signing import verify as _verify  # noqa: PLC0415

            parsed_url = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed_url.query)
            type_filter = params.get("type", [None])[0]
            try:
                offset = max(0, int(params.get("offset", ["0"])[0]))
            except (ValueError, TypeError):
                offset = 0
            try:
                limit = min(
                    max(1, int(params.get("limit", [str(_MAX_EVENTS_PER_LIST)])[0])),
                    _MAX_EVENTS_PER_LIST,
                )
            except (ValueError, TypeError):
                limit = _MAX_EVENTS_PER_LIST

            _COMPLIANCE_PREFIXES = ("llm.audit", "llm.guard", "llm.redact", "llm.compliance")

            store = self._get_store()
            all_events: list[Any] = []
            with store._lock:
                for evts in store._traces.values():
                    all_events.extend(evts)

            # Namespace prefix matching
            if type_filter:
                prefix = type_filter.lower()
                all_events = [
                    e for e in all_events
                    if str(getattr(e, "event_type", "")).lower().startswith(prefix)
                ]
            else:
                # Return all compliance-relevant events
                all_events = [
                    e for e in all_events
                    if any(
                        str(getattr(e, "event_type", "")).lower().startswith(p)
                        for p in _COMPLIANCE_PREFIXES
                    )
                ]

            all_events.sort(
                key=lambda e: getattr(e, "timestamp", 0),
                reverse=True,
            )
            total = len(all_events)
            subset = all_events[offset:offset + limit]

            org_secret = _os.environ.get("SPANFORGE_SIGNING_KEY", "")

            serialised: list[dict[str, Any]] = []
            for ev in subset:
                d = _serialise_event(ev)
                # GA-02-B: Add hmac_valid per event
                if org_secret and getattr(ev, "signature", None):
                    try:
                        d["hmac_valid"] = _verify(ev, org_secret)
                    except Exception:  # noqa: BLE001
                        d["hmac_valid"] = False
                else:
                    d["hmac_valid"] = None  # unsigned or no key
                serialised.append(d)

            self._json_response({
                "type_filter": type_filter,
                "event_count": len(serialised),
                "total": total,
                "offset": offset,
                "limit": limit,
                "events": serialised,
            })
        except Exception:  # NOSONAR
            _log.exception("compliance_events error")
            self._error(500, "Internal Server Error")

    # ------------------------------------------------------------------
    # Wire helpers
    # ------------------------------------------------------------------

    def _html_response(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_response(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode("utf-8")
        cors = getattr(self, "_cors_origins", "")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cors:
            self.send_header("Access-Control-Allow-Origin", cors)
        self.end_headers()
        self.wfile.write(body)

    def _text_response(self, text: str, status: int = 200) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._json_response({"error": message}, status=status)

    def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover
        pass  # suppress default access log


def _serialise_event(event: Any) -> dict[str, Any]:
    """Convert an Event to a plain dict (best-effort)."""
    if hasattr(event, "to_dict"):
        try:
            return event.to_dict()  # type: ignore[return-value]
        except Exception:  # NOSONAR
            pass
    return {
        "event_type": str(getattr(event, "event_type", "unknown")),
        "payload": getattr(event, "payload", {}),
        "timestamp": getattr(event, "timestamp", None),
        "span_id": getattr(event, "span_id", None),
        "trace_id": getattr(event, "trace_id", None),
    }


# ---------------------------------------------------------------------------
# TraceViewerServer
# ---------------------------------------------------------------------------


class TraceViewerServer:
    """Lightweight HTTP server exposing the in-process trace store as JSON.

    Args:
        port: TCP port to bind (default ``8888``).
        host: Interface to bind (default ``"127.0.0.1"``).
        store: Optional explicit :class:`~spanforge._store.TraceStore`
               instance.  If ``None``, uses the global singleton.

    Example::

        server = TraceViewerServer(port=8888)
        server.start()
        print("Browse traces at http://localhost:8888/traces")
        # ...
        server.stop()
    """

    def __init__(
        self,
        *,
        port: int = 8888,
        host: str = "127.0.0.1",
        store: Any = None,
        cors_origins: str = "",
    ) -> None:
        self._port = port
        self._host = host
        self._store = store
        self._cors_origins = cors_origins
        self._server: http.server.HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def _get_store(self) -> Any:
        if self._store is not None:
            return self._store
        from spanforge._store import get_store  # noqa: PLC0415
        return get_store()

    def start(self) -> None:
        """Start the viewer server in a background daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return  # already running

        get_store_fn = self._get_store
        cors = self._cors_origins

        class _Handler(_TraceAPIHandler):
            pass

        _Handler._get_store = staticmethod(get_store_fn)  # type: ignore[attr-defined]
        _Handler._cors_origins = cors  # type: ignore[attr-defined]

        self._server = http.server.HTTPServer((self._host, self._port), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"spanforge-viewer-{self._port}",
            daemon=True,
        )
        self._thread.start()
        _log.info(
            "spanforge trace viewer running at http://%s:%d",
            self._host,
            self._port,
        )
        print(
            f"[spanforge] Trace viewer: http://{self._host}:{self._port}/traces"
        )

    def stop(self) -> None:
        """Shut down the viewer server."""
        if self._server is not None:
            self._server.shutdown()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
