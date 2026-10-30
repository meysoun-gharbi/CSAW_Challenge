#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mission-control web console for the Challenge 1 agent (Serial Gateway).

Launches the agent (run_challenge1.py) as a subprocess, captures its live output,
and renders it in a professional page: status, real-time stats, attack progress,
colored stream (reasoning / decisions / UART oracle I/O), and a flag banner.

Run (UART over USB; normal internet for the LLM is fine):
    python.exe ch1_web.py --port COM4 --backend gemini --model gemini-flash-latest
Then open http://127.0.0.1:8011/
"""
from __future__ import annotations
import argparse, json, os, threading, subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Same LLM API setup as Challenge 3: load the project .env so the key is read
# from a gitignored file (not typed in clear), and use Gemini via Vertex AI by
# default (the key works on Vertex express mode, blocked on the Developer API).
try:
    from esc_agent.envfile import load_env
    load_env()
except Exception:
    pass

ap = argparse.ArgumentParser()
ap.add_argument("--port", default="COM4", help="serial port (COM4, /dev/ttyUSB0...)")
ap.add_argument("--backend", default="gemini", choices=["gemini", "claude", "mock"])
ap.add_argument("--model", default="gemini-2.5-flash")          # same model as CH3
ap.add_argument("--max-steps", type=int, default=400)
ap.add_argument("--listen", type=int, default=8011)
ap.add_argument("--no-vertex", dest="vertex", action="store_false", default=True,
                help="disable Vertex AI and use the Gemini Developer API instead "
                     "(Vertex is ON by default, like CH3)")
ap.add_argument("--python", default="python.exe",
                help="interpreter for the agent (needs pyserial + COM access)")
ap.add_argument("--autostart", action="store_true", help="start the agent on page load")
args = ap.parse_args()

LINES: list[str] = []
_proc = {"p": None}
_lock = threading.Lock()


def _emit(line: str):
    with _lock:
        LINES.append(line)


def start_agent():
    if _proc["p"] and _proc["p"].poll() is None:
        _emit("[web] agent already running.")
        return
    cmd = [args.python, "-u", "run_challenge1.py",
           "--port", args.port, "--backend", args.backend, "--model", args.model,
           "--max-steps", str(args.max_steps)]
    env = dict(os.environ)
    if args.vertex:
        env["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
    _emit("[web] launching: " + " ".join(cmd) + (" (Vertex)" if args.vertex else ""))
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", bufsize=1, env=env)
    except Exception as e:
        _emit(f"[web] LAUNCH ERROR: {e}")
        return
    _proc["p"] = p

    def reader():
        for line in p.stdout:
            _emit(line.rstrip("\n"))
        _emit(f"[web] agent finished (exit code {p.wait()}).")
    threading.Thread(target=reader, daemon=True).start()


PAGE = r"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Serial Gateway — Agent</title>
<style>
:root{
 --bg:#070b16; --bg2:#0b1222; --panel:#0e1627; --panel2:#111c30;
 --line:#1c2942; --ink:#e7eefc; --dim:#8695b3; --faint:#5b6b8c;
 --cyan:#36d6ff; --blue:#6aa6ff; --green:#39e6a0; --amber:#ffbf47;
 --red:#ff6b7d; --gold:#ffd66b; --violet:#b38cff;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%;overflow:hidden}
body{height:100vh;display:flex;flex-direction:column;background:
   radial-gradient(1200px 600px at 80% -10%,rgba(54,214,255,.10),transparent 60%),
   radial-gradient(900px 500px at -10% 110%,rgba(179,140,255,.10),transparent 60%),
   var(--bg);
 color:var(--ink);font:14px/1.45 ui-sans-serif,system-ui,"Segoe UI",Roboto,sans-serif;
 letter-spacing:.2px}
.mono{font-family:ui-monospace,"Cascadia Code",Consolas,Menlo,monospace}
a{color:var(--cyan)}

header{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:18px;
 padding:14px 22px;background:linear-gradient(180deg,rgba(10,16,30,.96),rgba(10,16,30,.82));
 border-bottom:1px solid var(--line);backdrop-filter:blur(6px)}
.badge{width:40px;height:40px;border-radius:11px;display:grid;place-items:center;
 background:linear-gradient(145deg,#12324a,#0b1b2e);border:1px solid #1d3b58;
 box-shadow:0 0 22px rgba(54,214,255,.25)}
.badge svg{width:22px;height:22px}
.h-t{font-weight:700;font-size:16px;letter-spacing:.6px}
.h-s{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:2px}
.spacer{flex:1}
.pill{display:flex;align-items:center;gap:8px;padding:7px 14px;border-radius:999px;
 border:1px solid var(--line);background:var(--panel);font-size:12px;font-weight:600;
 text-transform:uppercase;letter-spacing:1.5px}
.dot{width:9px;height:9px;border-radius:50%;background:var(--faint)}
.pill.idle .dot{background:var(--faint)}
.pill.run{border-color:#1d4a63;color:var(--cyan)}
.pill.run .dot{background:var(--cyan);box-shadow:0 0 10px var(--cyan);animation:pulse 1.1s infinite}
.pill.ok{border-color:#1c5a43;color:var(--green)}
.pill.ok .dot{background:var(--green);box-shadow:0 0 12px var(--green)}
.pill.err{border-color:#5a2730;color:var(--red)}
.pill.err .dot{background:var(--red)}
@keyframes pulse{50%{opacity:.35}}
.btn{cursor:pointer;border:0;border-radius:10px;padding:10px 20px;font:inherit;font-weight:700;
 letter-spacing:.5px;color:#04121f;background:linear-gradient(145deg,#4fe0ff,#3aa6ff);
 box-shadow:0 6px 20px rgba(54,214,255,.35)}
.btn:hover{filter:brightness(1.08)}
.btn:disabled{opacity:.5;cursor:default;box-shadow:none;filter:none}

main{flex:1;min-height:0;width:100%;max-width:1600px;margin:0 auto;padding:14px 20px 16px;
 display:flex;flex-direction:column;gap:12px}
.stats{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;flex:0 0 auto}
.tile{background:linear-gradient(160deg,var(--panel2),var(--panel));border:1px solid var(--line);
 border-radius:13px;padding:10px 14px}
.tile .k{color:var(--dim);font-size:10px;text-transform:uppercase;letter-spacing:1.6px}
.tile .v{font-size:23px;font-weight:700;margin-top:2px}
.tile .v small{font-size:12px;color:var(--faint);font-weight:500}
.tile.flag .v{color:var(--faint)}
.grid{flex:1;min-height:0;display:grid;grid-template-columns:1fr 340px;gap:14px}
@media(max-width:1000px){.stats{grid-template-columns:repeat(3,1fr)}.grid{grid-template-columns:1fr}}
.card{background:linear-gradient(160deg,var(--panel2),var(--panel));border:1px solid var(--line);
 border-radius:16px;overflow:hidden;display:flex;flex-direction:column;min-height:0}
.card>.hd{display:flex;align-items:center;gap:8px;padding:11px 15px;border-bottom:1px solid var(--line);
 font-size:11px;text-transform:uppercase;letter-spacing:2px;color:var(--dim)}
.card>.hd .d{width:7px;height:7px;border-radius:50%;background:var(--cyan)}

#term{flex:1;min-height:0;overflow:auto;padding:12px 15px;font-family:ui-monospace,Consolas,monospace;
 font-size:12.5px;line-height:1.55;background:
   linear-gradient(180deg,rgba(255,255,255,.015),transparent 2px) 0 0/100% 22px}
.ln{padding:1px 0;white-space:pre-wrap;word-break:break-word}
.ln .tag{display:inline-block;min-width:92px;color:var(--faint)}
.think{color:#b9c6e4;font-style:italic}
.act{color:var(--blue);font-weight:600}
.tx{color:var(--cyan)} .rx{color:var(--green)} .uart{color:var(--amber)}
.sys{color:var(--faint)}
.err{color:var(--red)}
.flagline{background:linear-gradient(90deg,rgba(57,230,160,.16),transparent);
 color:#aeffd4;font-weight:700;border-left:2px solid var(--green);padding-left:8px}
#term::-webkit-scrollbar{width:9px}
#term::-webkit-scrollbar-thumb{background:#223349;border-radius:9px}

.steps{padding:6px 6px;overflow:auto}
.step{display:flex;gap:11px;align-items:center;padding:7px 10px;border-radius:10px}
.step .ix{width:22px;height:22px;flex:0 0 22px;border-radius:50%;display:grid;place-items:center;
 font-size:11px;font-weight:700;border:1px solid var(--line);color:var(--faint);background:var(--bg2)}
.step .tt{font-weight:600;font-size:13px}
.step.on{background:rgba(54,214,255,.06)}
.step.on .ix{border-color:var(--cyan);color:var(--cyan);box-shadow:0 0 10px rgba(54,214,255,.4)}
.step.done .ix{background:var(--green);border-color:var(--green);color:#042;box-shadow:0 0 10px rgba(57,230,160,.5)}
.step.done .tt{color:var(--green)}
.probe{padding:12px 15px}
.probe .lbl{color:var(--dim);font-size:10px;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:4px}
.probe .val{font-family:ui-monospace,Consolas,monospace;font-size:13px;background:#060d1b;border:1px solid var(--line);
 border-radius:8px;padding:9px 11px;min-height:20px;word-break:break-word;margin-bottom:11px}
.probe .val.out{color:var(--green)}

#flag{display:none;margin:0 0 4px;padding:16px 20px;border-radius:16px;align-items:center;gap:14px;
 background:linear-gradient(135deg,rgba(57,230,160,.18),rgba(255,214,107,.10));
 border:1px solid #1f6b4e;box-shadow:0 0 36px rgba(57,230,160,.25)}
#flag.show{display:flex;animation:pop .5s ease}
@keyframes pop{from{transform:scale(.96);opacity:0}to{transform:scale(1);opacity:1}}
#flag .ico{font-size:26px}
#flag .ft{font-size:11px;text-transform:uppercase;letter-spacing:2px;color:var(--green)}
#flag .fv{font-family:ui-monospace,Consolas,monospace;font-size:18px;font-weight:700;color:#d8ffe9}
</style></head>
<body>
<header>
 <div class=badge><svg viewBox="0 0 24 24" fill="none" stroke="#4fe0ff" stroke-width="1.8"
   stroke-linecap="round" stroke-linejoin="round">
   <rect x="4" y="7" width="16" height="10" rx="2"/>
   <path d="M4 10h-2M4 14h-2M22 10h-2M22 14h-2M8 7V5M12 7V5M16 7V5M8 19v-2M12 19v-2M16 19v-2"/>
   <path d="M8 12h3l1 2 1-4 1 2h2" stroke="#39e6a0"/></svg></div>
 <div>
   <div class=h-t>SERIAL&nbsp;GATEWAY</div>
   <div class=h-s>CSAW ESC 2026 · Challenge 1 · UART Oracle → Flag</div>
 </div>
 <div class=spacer></div>
 <div class="pill idle" id=pill><span class=dot></span><span id=pillt>Ready</span></div>
 <button class=btn id=go onclick=start()>▶ Launch agent</button>
</header>

<main>
 <div id=flag><div class=ico>🏁</div><div><div class=ft>Flag captured</div>
   <div class=fv id=flagv></div></div></div>

 <div class=stats>
   <div class=tile><div class=k>Status</div><div class="v" id=s_state style="font-size:18px">—</div></div>
   <div class=tile><div class=k>UART requests</div><div class=v id=s_uart>0</div></div>
   <div class=tile><div class=k>Reboots</div><div class=v id=s_reboot>0</div></div>
   <div class=tile><div class=k>Agent steps</div><div class=v id=s_step>0</div></div>
   <div class=tile><div class=k>Elapsed</div><div class=v id=s_time>0<small>s</small></div></div>
   <div class="tile flag"><div class=k>Flag</div><div class=v id=s_flag>—</div></div>
 </div>

 <div class=grid>
   <div class=card>
     <div class=hd><span class=d></span>Agent stream — live reasoning &amp; actions
       <span class=spacer></span><span class=sys id=count style="letter-spacing:1px"></span></div>
     <div id=term class=mono></div>
   </div>
   <div style="display:flex;flex-direction:column;gap:14px;min-height:0;overflow:auto">
     <div class=card style="flex:0 0 auto">
       <div class=hd><span class=d></span>Progress</div>
       <div class=steps id=steps></div>
     </div>
     <div class=card>
       <div class=hd><span class=d></span>Last oracle query</div>
       <div class=probe>
         <div class=lbl>Sent</div><div class="val" id=p_in>—</div>
         <div class=lbl>Response</div><div class="val out" id=p_out>—</div>
       </div>
     </div>
   </div>
 </div>
</main>

<script>
const STEPS=[
 "Reconnaissance",
 "Oracle probing",
 "Command discovered",
 "Privilege unlock",
 "Flag captured"
];
const stepsEl=document.getElementById('steps');
STEPS.forEach((s,i)=>{stepsEl.insertAdjacentHTML('beforeend',
 `<div class=step id=st${i}><div class=ix>${i+1}</div><div class=tt>${s}</div></div>`);});
function stage(i,done){for(let k=0;k<=i;k++){const e=document.getElementById('st'+k);
 e.classList.add(k<i||done?'done':'on'); if(k<i)e.classList.remove('on');}
 if(done){document.getElementById('st'+i).classList.add('done');document.getElementById('st'+i).classList.remove('on');}}

const term=document.getElementById('term');
let off=0,started=null,solved=false,ended=false;
let nUart=0,nReboot=0,nStep=0,maxStage=-1;
const esc=s=>(s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const flagRe=/((esc_2026|ESC)\{[^}]*\})/i;

function setPill(cls,txt){const p=document.getElementById('pill');p.className='pill '+cls;
 document.getElementById('pillt').textContent=txt;document.getElementById('s_state').textContent=txt;}

function classify(l){
 if(flagRe.test(l))return'flagline';
 if(l.startsWith('[thought'))return'think';
 if(l.startsWith('[tool'))return'act';
 if(l.startsWith('[web]'))return'sys';
 if(/^---.*reboot/i.test(l)||/reboot|penalite|rate.?limit/i.test(l)&&l.startsWith('---'))return'uart';
 if(/error|ERROR|Traceback|refus/i.test(l))return'err';
 if(l.startsWith('>>>'))return'tx';
 if(l.startsWith('<<<'))return'rx';
 return'sys';
}
function split(l){
 let m=l.match(/^(\[thought\]|\[tool -> [^\]]+\])\s*([\s\S]*)$/);
 if(m)return[m[1],m[2]];
 m=l.match(/^(>>>|<<<)\s*([\s\S]*)$/);
 if(m)return[m[1],m[2]];
 return['',l];
}
function handle(l){
 if(l.startsWith('[thought'))nStep++;
 if(l.startsWith('>>>'))nUart++,bump(1);
 if(/^---.*reboot/i.test(l)||l.startsWith('--- reboot'))nReboot++;
 if(/wifi_scan|boot|banner|scan/i.test(l))bump(0);
 // a <<< response that is NOT the prefix-oracle message => a real command executed
 if(l.startsWith('<<<')&&!/command.{0,6}start|no command|starts with/i.test(l)&&l.replace('<<<','').trim().length>1)bump(2);
 if(/<<<[\s\S]*(dev|unlock|mode|grant|enabl|privile|access|admin|root|secret)/i.test(l))bump(3);
 const fm=l.match(flagRe);
 if(fm){bump(4,true);solved=true;showFlag(fm[1]);}
}
function bump(i,done){ if(i>maxStage){maxStage=i;} stage(Math.max(maxStage,i),!!done); }
function showFlag(f){
 document.getElementById('flagv').textContent=f;
 document.getElementById('flag').classList.add('show');
 document.getElementById('s_flag').textContent='✔';
 document.querySelector('.tile.flag .v').style.color='var(--green)';
 setPill('ok','Solved');
}
function render(lines){
 for(const l of lines){
  handle(l);
  const [tag,rest]=split(l);
  const d=document.createElement('div');d.className='ln '+classify(l);
  d.innerHTML=tag?`<span class=tag>${esc(tag)}</span>${esc(rest)}`:esc(l);
  term.appendChild(d);
  if(l.startsWith('>>>'))document.getElementById('p_in').textContent=rest||l;
  if(l.startsWith('<<<'))document.getElementById('p_out').textContent=rest||l;
  if(l.includes('agent finished'))ended=true;
 }
 if(lines.length){term.scrollTop=term.scrollHeight;
  document.getElementById('s_uart').textContent=nUart;
  document.getElementById('s_reboot').textContent=nReboot;
  document.getElementById('s_step').textContent=nStep;
  document.getElementById('count').textContent=off+' lines';}
 if(!solved){ if(ended)setPill('err','Finished'); else if(started)setPill('run','Running'); }
}
async function start(){
 document.getElementById('go').disabled=true;
 setPill('run','Starting…'); started=started||Date.now();
 await fetch('/start',{method:'POST'});
}
async function poll(){
 try{const j=await(await fetch('/feed?offset='+off)).json();off=j.offset;
  if(j.lines.length){ if(!started)started=Date.now(); render(j.lines);} }catch(e){}
 if(started&&!ended){const s=Math.floor((Date.now()-started)/1000);
  document.querySelector('#s_time').innerHTML=s+'<small>s</small>';}
 setTimeout(poll,350);
}
setPill('idle','Ready');
poll();
/*AUTOSTART*/
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/start":
            start_agent()
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        self.send_response(404); self.end_headers()

    def do_GET(self):
        if self.path.startswith("/feed"):
            from urllib.parse import urlparse, parse_qs
            off = int(parse_qs(urlparse(self.path).query).get("offset", ["0"])[0])
            with _lock:
                lines = LINES[off:]; newoff = len(LINES)
            body = json.dumps({"offset": newoff, "lines": lines}).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.end_headers(); self.wfile.write(body); return
        page = PAGE.replace("/*AUTOSTART*/", "start();" if args.autostart else "")
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers(); self.wfile.write(page.encode("utf-8"))

    def log_message(self, *a):
        pass


print(f"Web console: http://127.0.0.1:{args.listen}/   (agent {args.backend}/{args.model}, port {args.port}"
      + (", Vertex" if args.vertex else "") + ")")
print("Open the page and click 'Launch agent'. Ctrl+C to stop.")
if args.autostart:
    start_agent()
try:
    ThreadingHTTPServer(("127.0.0.1", args.listen), H).serve_forever()
except KeyboardInterrupt:
    if _proc["p"]:
        _proc["p"].terminate()
    print("\nstopped.")
