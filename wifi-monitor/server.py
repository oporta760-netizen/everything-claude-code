#!/usr/bin/env python3
"""Quién está en mi WiFi: escanea tu red local y muestra los dispositivos.
Uso: python3 server.py   ->  abre http://localhost:8080
Solo usa la librería estándar. Funciona en Linux, macOS y Windows."""
import ipaddress, json, platform, re, socket, subprocess, threading, time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8080
IS_WIN = platform.system() == "Windows"
state = {"devices": [], "updated": 0, "scanning": False, "subnet": ""}
first_seen = {}

def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80)); return s.getsockname()[0]
    finally:
        s.close()

def ping(ip):
    cmd = ["ping", "-n", "1", "-w", "700", ip] if IS_WIN else \
          ["ping", "-c", "1", "-W", "1", ip]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def arp_table():
    out = {}
    try:
        txt = subprocess.run(["arp", "-a"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        txt = open("/proc/net/arp").read()
    for line in txt.splitlines():
        ip = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
        mac = re.search(r"((?:[0-9a-fA-F]{1,2}[:-]){5}[0-9a-fA-F]{1,2})", line)
        if ip and mac:
            m = ":".join(p.zfill(2) for p in re.split(r"[:-]", mac.group(1))).lower()
            if m not in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
                out[ip.group(1)] = m
    return out

def hostname(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ""

def scan():
    if state["scanning"]:
        return
    state["scanning"] = True
    try:
        me = local_ip()
        net = ipaddress.ip_network(me + "/24", strict=False)
        state["subnet"] = str(net)
        hosts = [str(h) for h in net.hosts()]
        with ThreadPoolExecutor(64) as ex:
            list(ex.map(ping, hosts))
        table = arp_table()
        table.setdefault(me, "(este equipo)")
        gw = ""
        with ThreadPoolExecutor(32) as ex:
            names = dict(zip(table, ex.map(hostname, table)))
        now = time.time()
        devs = []
        for ip, mac in sorted(table.items(), key=lambda x: ipaddress.ip_address(x[0])):
            if ipaddress.ip_address(ip) not in net:
                continue
            first_seen.setdefault(mac if mac[0] != "(" else ip, now)
            devs.append({"ip": ip, "mac": mac, "name": names.get(ip, ""),
                         "me": ip == me,
                         "private_mac": mac[1] in "26ae" if mac[0] != "(" else False,
                         "since": first_seen[mac if mac[0] != "(" else ip]})
        state["devices"], state["updated"] = devs, now
    finally:
        state["scanning"] = False

def loop():
    while True:
        scan(); time.sleep(30)

PAGE = """<!doctype html><html lang="es"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quién está en mi WiFi</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--tx:#1b1f24;--mu:#6b7280;--ac:#2563eb;--bd:#e5e7eb}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--tx:#e6e8eb;--mu:#8b93a1;--ac:#60a5fa;--bd:#262b35}}
body{margin:0;background:var(--bg);color:var(--tx);font:15px system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--mu);margin-bottom:16px}
.top{display:flex;gap:12px;align-items:center;margin-bottom:16px;flex-wrap:wrap}
.count{font-size:34px;font-weight:700;color:var(--ac)}
button{background:var(--ac);color:#fff;border:0;border-radius:8px;padding:8px 14px;font:inherit;cursor:pointer}
input{padding:8px 10px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--tx);font:inherit;flex:1;min-width:160px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--bd);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--bd)}
th{font-size:12px;text-transform:uppercase;color:var(--mu)}
td.mono{font-family:ui-monospace,monospace;font-size:13px}
.tag{font-size:11px;padding:2px 6px;border-radius:6px;background:var(--bd);color:var(--mu);margin-left:6px}
@media(max-width:600px){.hide{display:none}}
</style>
<main>
<h1>Quién está en mi WiFi</h1>
<div class="sub" id="sub">Escaneando…</div>
<div class="top"><div><span class="count" id="n">–</span> dispositivos</div>
<input id="q" placeholder="Filtrar por IP, MAC o nombre…"><button id="b">Escanear ahora</button></div>
<table><thead><tr><th>IP</th><th>Nombre</th><th class="hide">MAC</th><th class="hide">Visto desde</th></tr></thead>
<tbody id="t"></tbody></table>
<p class="sub">Una MAC “privada” es una dirección aleatoria que usan iPhone/Android para no ser rastreados. Si ves un dispositivo que no reconoces, cambia la clave del WiFi.</p>
</main>
<script>
let data=[];
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function draw(){const q=document.getElementById('q').value.toLowerCase();
const rows=data.devices.filter(d=>(d.ip+d.mac+d.name).toLowerCase().includes(q));
document.getElementById('n').textContent=data.devices.length;
document.getElementById('t').innerHTML=rows.map(d=>`<tr><td class="mono">${esc(d.ip)}${d.me?'<span class="tag">tú</span>':''}</td>
<td>${esc(d.name||'Desconocido')}${d.private_mac?'<span class="tag">MAC privada</span>':''}</td>
<td class="mono hide">${esc(d.mac)}</td><td class="hide">${new Date(d.since*1000).toLocaleTimeString()}</td></tr>`).join('');
document.getElementById('sub').textContent=(data.scanning?'Escaneando… ':'')+'Red '+data.subnet+(data.updated?' · actualizado '+new Date(data.updated*1000).toLocaleTimeString():'')}
async function load(){data=await (await fetch('/api/devices')).json();draw()}
document.getElementById('q').oninput=draw;
document.getElementById('b').onclick=async()=>{await fetch('/api/scan',{method:'POST'});setTimeout(load,500)};
load();setInterval(load,5000);
</script></html>"""

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, body, ctype):
        b = body.encode(); self.send_response(200)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/api/devices": self.send(json.dumps(state), "application/json")
        else: self.send(PAGE, "text/html; charset=utf-8")
    def do_POST(self):
        threading.Thread(target=scan, daemon=True).start(); self.send("{}", "application/json")

if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    print(f"Abre http://localhost:{PORT}  (Ctrl+C para salir)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
