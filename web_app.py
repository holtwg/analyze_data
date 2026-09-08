#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""竞彩赔率分析 Web 服务（零额外依赖，仅标准库 + 项目 src 模块）。

启动：
    python web_app.py            # 默认端口 8000
    python web_app.py 9000       # 指定端口

访问：
    http://localhost:8000

功能与 gui.py / nba_gui.py 一致：在网页上选择足球/篮球，输入场次号或比赛 ID，
点击「分析」即在页面显示分析结果（足球胜平负概率/体彩价值；篮球胜负/让分）。
"""
from __future__ import annotations

import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>竞彩赔率分析 Web</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Microsoft YaHei", "PingFang SC", sans-serif;
         max-width: 920px; margin: 0 auto; padding: 24px; background: #f4f6f9; color: #1f2329; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .sub { color: #8a9099; font-size: 13px; margin-bottom: 16px; }
  .card { background: #fff; border-radius: 12px; padding: 22px;
          box-shadow: 0 1px 6px rgba(0,0,0,.08); }
  .tabs { display: flex; gap: 8px; margin-bottom: 16px; }
  .tab { padding: 8px 18px; border: 1px solid #d9dde3; border-radius: 8px;
         cursor: pointer; background: #fafbfc; font-size: 14px; user-select: none; }
  .tab.active { background: #2d6cdf; color: #fff; border-color: #2d6cdf; }
  .row { display: flex; gap: 10px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
  input[type=text] { flex: 1; min-width: 220px; padding: 10px 12px;
                     border: 1px solid #ccd2da; border-radius: 8px; font-size: 14px; }
  select { padding: 9px 10px; border: 1px solid #ccd2da; border-radius: 8px; font-size: 14px; }
  button.go { padding: 10px 24px; background: #2d6cdf; color: #fff; border: none;
              border-radius: 8px; font-size: 15px; cursor: pointer; }
  button.go:disabled { opacity: .55; cursor: default; }
  .note { color: #6b7280; font-size: 13px; margin: 4px 0 10px; min-height: 18px; }
  pre { background: #1e1e1e; color: #e6e6e6; padding: 18px; border-radius: 10px;
        overflow: auto; white-space: pre-wrap; word-break: break-word;
        font-size: 13px; line-height: 1.55; min-height: 160px; margin: 0; }
  .foot { color: #aab; font-size: 12px; margin-top: 14px; text-align: center; }
  code { background:#eef1f5; padding:1px 5px; border-radius:4px; }
</style>
</head>
<body>
<div class="card">
  <h1>竞彩赔率分析 Web</h1>
  <div class="sub">足球/篮球 胜平负 &amp; 让分方向概率 · 体彩价值研判</div>

  <div class="tabs">
    <div class="tab active" data-kind="football" onclick="switchKind('football')">足球</div>
    <div class="tab" data-kind="nba" onclick="switchKind('nba')">篮球</div>
  </div>

  <div class="row">
    <input type="text" id="ref" placeholder="输入场次，如 周六015 / 3000426 / oddslist 链接" />
    <select id="mode" style="display:none">
      <option value="ml">胜负</option>
      <option value="spread">让分</option>
      <option value="both">两者</option>
    </select>
    <button class="go" id="goBtn" onclick="run()">分析</button>
  </div>
  <div class="note" id="note"></div>
  <pre id="out">在上方输入场次后点击「分析」。</pre>
  <div class="foot">结果仅供参考，非赛果预测，不构成投资建议。</div>
</div>

<script>
let kind = 'football';
function switchKind(k){
  kind = k;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.kind === k));
  document.getElementById('mode').style.display = (k === 'nba') ? 'inline-block' : 'none';
  document.getElementById('ref').placeholder = (k === 'nba')
    ? '输入场次，如 周六301 / 705225'
    : '输入场次，如 周六015 / 3000426 / oddslist 链接';
}
async function run(){
  const ref = document.getElementById('ref').value.trim();
  if(!ref){ alert('请输入场次'); return; }
  const mode = document.getElementById('mode').value;
  const btn = document.getElementById('goBtn');
  btn.disabled = true; btn.textContent = '分析中...';
  document.getElementById('out').textContent = '抓取数据中，请稍候...';
  document.getElementById('note').textContent = '';
  try{
    const resp = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, ref, mode })
    });
    const data = await resp.json();
    if(data.ok){
      document.getElementById('note').textContent = data.note || '';
      document.getElementById('out').textContent = data.report;
    } else {
      document.getElementById('out').textContent = '分析失败：' + data.error;
    }
  }catch(e){
    document.getElementById('out').textContent = '请求失败：' + e;
  }finally{
    btn.disabled = false; btn.textContent = '分析';
  }
}
document.getElementById('ref').addEventListener('keydown', function(e){
  if(e.key === 'Enter') run();
});
</script>
</body>
</html>
"""


def _nba_hist(mid: str, target_date: str | None):
    """尝试从历史汇总接口取该场记录（兜底用）。"""
    if not target_date:
        return None
    try:
        from src.nba_history import fetch_nba_history_records
        return fetch_nba_history_records(target_date).get(mid)
    except Exception:
        return None


def build_report(kind: str, ref: str, mode: str):
    """根据类型/场次/模式生成分析报告文本。返回 (report_text, note_text)。"""
    if kind == "football":
        from src.schedule import resolve_match_ref
        from src.odds import fetch_match_odds
        from src.analysis import analyze, format_report
        from src.football_asian_odds import fetch_football_asian
        resolved = resolve_match_ref(ref)
        mid = str(resolved["match_id"])
        match = fetch_match_odds(mid)
        # 亚盘数据（欧亚一致性用），抓取失败不影响欧赔分析
        asian = None
        try:
            asian = fetch_football_asian(mid)
        except Exception:
            asian = None
        report = format_report(analyze(match, asian=asian))
        note = f"解析：{resolved['source']} -> ID {mid}"
        if resolved.get("label"):
            note += f"  （{resolved['label']}"
            if resolved.get("target_date"):
                note += f"，{resolved['target_date']}"
            note += "）"
        if resolved.get("note"):
            note += f"  | 提示：{resolved['note']}"
        return report, note

    # 篮球
    from src.nba_schedule import resolve_nba_ref
    from src.nba_odds import fetch_nba_match_odds
    from src.nba_analysis import analyze_nba, format_nba_report
    from src.nba_spread_odds import fetch_nba_spread
    from src.nba_spread_analysis import analyze_nba_spread, format_nba_spread_report
    from src.nba_history import format_nba_history_report

    resolved = resolve_nba_ref(ref)
    mid = str(resolved["match_id"])
    target_date = resolved.get("target_date")
    note = f"解析：{resolved['source']} -> ID {mid}"
    if resolved.get("label"):
        note += f"  （{resolved['label']}"
        if target_date:
            note += f"，{target_date}"
        note += "）"
    if resolved.get("note"):
        note += f"  | 提示：{resolved['note']}"

    parts: list[str] = []
    ml_result = None

    # 胜负（moneyline）
    try:
        match = fetch_nba_match_odds(mid)
        ml_result = analyze_nba(match)
        parts.append(format_nba_report(ml_result))
    except Exception:
        rec = _nba_hist(mid, target_date)
        if rec is not None:
            parts.append(format_nba_history_report(rec))

    # 让分（spread）
    if mode in ("spread", "both"):
        try:
            smatch = fetch_nba_spread(mid)
            parts.append(format_nba_spread_report(analyze_nba_spread(smatch, ml_result=ml_result)))
        except Exception:
            rec = _nba_hist(mid, target_date)
            if rec is not None:
                parts.append(format_nba_history_report(rec))

    if not parts:
        raise RuntimeError(
            f"比赛 {mid} 暂无可用数据（实时接口不可达且无对应历史赛果记录）。"
        )
    return "\n".join(parts), note


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: str, ctype: str = "application/json; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, INDEX_HTML, "text/html; charset=utf-8")
        elif path == "/healthz":
            self._send(200, json.dumps({"ok": True}, ensure_ascii=False))
        else:
            self._send(404, json.dumps({"ok": False, "error": "Not found"}, ensure_ascii=False))

    def do_POST(self):
        if self.path.split("?")[0] != "/api/analyze":
            self._send(404, json.dumps({"ok": False, "error": "Not found"}, ensure_ascii=False))
            return
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw) if raw else {}
            kind = payload.get("kind", "football")
            ref = (payload.get("ref") or "").strip()
            mode = payload.get("mode", "ml")
            if not ref:
                self._send(400, json.dumps({"ok": False, "error": "场次不能为空"}, ensure_ascii=False))
                return
            report, note = build_report(kind, ref, mode)
            self._send(200, json.dumps({"ok": True, "report": report, "note": note}, ensure_ascii=False))
        except Exception as exc:  # 任何分析/抓取异常都回传错误文本，不让页面崩
            self._send(200, json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))

    def log_message(self, *args):  # 静默访问日志
        pass


def main() -> None:
    # PaaS（Railway/Render/Heroku）通过 PORT 环境变量注入端口；本地可用 python web_app.py 9000 覆盖
    port = int(os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else 8000))
    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    print(f"竞彩分析 Web 已启动：监听 0.0.0.0:{port}")
    print(f"本地访问 http://localhost:{port} ；PaaS 环境由平台分配公网地址。按 Ctrl+C 停止。")
    try:
        webbrowser.open(f"http://localhost:{port}")
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
