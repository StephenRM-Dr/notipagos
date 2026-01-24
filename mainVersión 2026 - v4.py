import psycopg2
import re
import os
import pandas as pd
import pytz # Librería para manejar zonas horarias
from flask import Flask, request, render_template_string, redirect, url_for, session, send_file
from datetime import datetime
from io import BytesIO
from dotenv import load_dotenv

# --- CONFIGURACIÓN ---
load_dotenv(override=True)
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "clave_sistemas_mv_2026")

# Definición de Zona Horaria de Venezuela
VET = pytz.timezone('America/Caracas')

# --- CONEXIÓN BASE DE DATOS ---
def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        port=os.getenv("DB_PORT", "5432"),
        sslmode="require" if "neon.tech" in (os.getenv("DB_HOST") or "") else "disable"
    )

# --- EXTRACTOR INTELIGENTE (Versión v10 - Optimizada para Sofitasa y Plaza) ---
def extractor_inteligente(texto):
    # El programa usa un limpiador de texto [2026-01-16]
    texto_limpio = texto.replace('"', '').replace('\\n', ' ').replace('\n', ' ').strip()
    pagos_detectados = []
    
    patrones = {
        "BDV": (r"BDV|PagomovilBDV", r"(?:del|tlf|desde el tlf)\s*(\d+)", r"(?:por|Bs\.?|Monto:)\s*([\d.]+,\d{2})", r"Ref:\s*(\d+)"),
        "BANESCO": (r"Banesco", r"(?:de|desde|tlf)\s*(\d+)", r"(?:Bs\.?|Monto:?)\s*([\d.]+,\d{2})", r"Ref:\s*(\d+)"),
        "SOFITASA": (r"SOFITASA", r"Telf\.?([\d*]+)", r"Bs\.?\s*([\d,.]+)", r"Ref:(\d+)"),
        "BINANCE": (r"Binance", r"(?:from|de)\s+(.*?)\s", r"([\d.]+)\s*USDT", r"(?:ID|Order)[:\s]+(\d+)"),
        "PLAZA": (r"Plaza", r"Celular\s+([\d]+)", r"(?:BS\.?|por)\s*([\d,.]+)", r"Ref[\.:]\s*(\d+)")
    }

    for banco, (key, re_emi, re_mon, re_ref) in patrones.items():
        if re.search(key, texto_limpio, re.IGNORECASE):
            m_emi = re.search(re_emi, texto_limpio, re.IGNORECASE)
            m_mon = re.search(re_mon, texto_limpio, re.IGNORECASE)
            m_ref = re.search(re_ref, texto_limpio, re.IGNORECASE)
            if m_ref:
                monto_raw = m_mon.group(1) if m_mon else "0,00"
                pagos_detectados.append({
                    "banco": banco, 
                    "emisor": m_emi.group(1) if m_emi else "S/D", 
                    "monto": monto_raw, 
                    "referencia": m_ref.group(1),
                    "original": texto_limpio
                })
    return pagos_detectados

# --- ESTILOS CSS (DISEÑO PREMIUM, RESPONSIVE Y CENTRADO) ---
CSS_FINAL = '''
:root { 
    --primary: #004481; --secondary: #f4f7f9; --danger: #d9534f; --success: #28a745; --warning: #ffc107;
    --bdv: #D32F2F; --banesco: #007A33; --binance: #F3BA2F; --plaza: #005691; --sofitasa: #0097A7;
}
* { box-sizing: border-box; }
body { font-family: 'Segoe UI', sans-serif; background: var(--secondary); margin: 0; min-height: 100vh; display: flex; flex-direction: column; }
.container { width: 100%; max-width: 1250px; margin: auto; padding: 20px; flex: 1; }
.card { background: white; border-radius: 18px; box-shadow: 0 10px 30px rgba(0,0,0,0.08); padding: 30px; margin-bottom: 25px; text-align: center; }
.nav-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; flex-wrap: wrap; gap: 15px; }
.btn { border: none; border-radius: 12px; padding: 14px 24px; font-weight: 700; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; gap: 10px; transition: 0.3s; justify-content: center; font-size: 14px; }
.btn-primary { background: var(--primary); color: white; }
.btn-light { background: #fff; color: #555; border: 1px solid #ddd; }
.btn-danger { background: var(--danger); color: white; }
.btn-success { background: var(--success); color: white; }
.btn-warning { background: var(--warning); color: #333; }
.table-wrapper { width: 100%; overflow-x: auto; background: white; border-radius: 18px; border: 1px solid #eee; }
table { width: 100%; border-collapse: collapse; min-width: 1100px; text-align: center; }
th { background: #fcfcfc; padding: 18px; font-size: 11px; color: #888; border-bottom: 2px solid #eee; text-transform: uppercase; }
td { padding: 18px; border-bottom: 1px solid #f1f1f1; font-size: 13px; vertical-align: middle; }
.badge { padding: 8px 16px; border-radius: 25px; font-weight: bold; font-size: 10px; text-transform: uppercase; color: white; display: inline-block; }
.badge-bdv { background: var(--bdv); } .badge-sofitasa { background: var(--sofitasa); } .badge-plaza { background: var(--plaza); } .badge-binance { background: var(--binance); color: #000; } .badge-banesco { background: var(--banesco); }
.grid-totales { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 20px; margin-top: 25px; }
.total-item { padding: 25px; border-radius: 20px; color: white; font-weight: bold; font-size: 20px; box-shadow: 0 5px 15px rgba(0,0,0,0.1); }
input { border: 2px solid #eee; border-radius: 12px; padding: 15px; outline: none; width: 100%; text-align: center; font-size: 16px; transition: 0.3s; }
input:focus { border-color: var(--primary); background: #fdfdfd; }
.notif-pago { border-radius: 15px; padding: 25px; margin-top: 25px; border: 1px solid rgba(0,0,0,0.05); text-align: left; }
.notif-success { background: #e8f5e9; border-left: 6px solid var(--success); color: #1b5e20; }
.notif-error { background: #ffebee; border-left: 6px solid var(--danger); color: #b71c1c; }
.notif-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 15px; }
.notif-item { background: rgba(255,255,255,0.6); padding: 10px; border-radius: 10px; }
.notif-label { font-size: 9px; text-transform: uppercase; opacity: 0.8; display: block; font-weight: bold; }
@media (max-width: 600px) { .nav-header { justify-content: center; } .btn { width: 100%; } .notif-grid { grid-template-columns: 1fr; } }
'''

# --- VISTAS HTML ---
HTML_LOGIN = '''<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>''' + CSS_FINAL + '''</style></head><body><div style="display:flex; align-items:center; justify-content:center; min-height:100vh; background: radial-gradient(circle at top, #004481 0%, #001a33 100%); padding: 20px;"><div class="card" style="width:100%; max-width:420px; border:none;"> <h1 style="color:var(--primary); margin-bottom:5px;">SISTEMAS MV</h1><p style="color:#777; margin-bottom:25px;">Control Administrativo v2026</p><form method="POST"><input type="password" name="password" placeholder="PIN de Seguridad" style="margin-bottom:20px;" autofocus required><button class="btn btn-primary" style="width:100%;">ENTRAR AL SISTEMA</button></form><hr style="margin:25px 0; border:0; border-top:1px solid #eee;"><a href="/" class="btn btn-light" style="width:100%;">🔍 IR AL VERIFICADOR</a></div></div></body></html>'''

HTML_PORTAL = '''<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>''' + CSS_FINAL + '''</style></head><body><div class="container" style="max-width:550px; margin-top:40px;"><div class="nav-header"><a href="/" class="btn btn-light">🔄 Recargar</a><a href="/admin" class="btn btn-primary">⚙️ Acceso Admin</a></div><div class="card"><h2>Verificar Transacción</h2><p style="color:#888; font-size:14px; margin-bottom:25px;">Ingrese los datos para validar su comanda</p><form method="POST" action="/verificar"><input type="text" name="ref" placeholder="Nro de Referencia" style="margin-bottom:15px;" required><input type="text" name="comanda" placeholder="Nro de Comanda / Orden" style="margin-bottom:25px;" required><button class="btn btn-primary" style="width:100%; padding:18px;">VALIDAR AHORA</button></form>
{% if resultado %}
    <div class="notif-pago notif-{{ resultado.clase }}">
        <div style="display:flex; align-items:center; gap:10px;"><strong style="font-size:18px;">{{ resultado.titulo }}</strong></div>
        <p style="margin:10px 0; font-size:14px;">{{ resultado.mensaje }}</p>
        {% if resultado.datos %}
        <div class="notif-grid">
            <div class="notif-item"><span class="notif-label">Banco</span><strong>{{ resultado.datos.banco }}</strong></div>
            <div class="notif-item"><span class="notif-label">Monto</span><strong>Bs. {{ resultado.datos.monto }}</strong></div>
            <div class="notif-item"><span class="notif-label">Referencia</span><code>{{ resultado.datos.ref }}</code></div>
            <div class="notif-item"><span class="notif-label">Comanda</span><strong>#{{ resultado.datos.comanda }}</strong></div>
            <div class="notif-item" style="grid-column: span 2;"><span class="notif-label">Auditoría VET (Hora Local)</span><small>{{ resultado.datos.fecha }} | IP: {{ resultado.datos.ip }}</small></div>
        </div>
        {% endif %}
    </div>
{% endif %}
</div></div></body></html>'''

HTML_ADMIN = '''<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>''' + CSS_FINAL + '''</style></head><body><div class="container"><div class="nav-header"><h2>Panel de Control</h2><div style="display:flex; gap:10px; flex-wrap:wrap;"><a href="/" class="btn btn-light">🔍 Verificador</a><a href="/admin/exportar" class="btn btn-success">Excel</a><a href="/logout" class="btn btn-danger">Salir</a></div></div><div class="card" style="padding:15px;"><input type="text" id="busc" placeholder="🔍 Filtrar registros..." onkeyup="f()"></div><div class="table-wrapper"><table id="tab"><thead><tr><th>Recepción (VET)</th><th>Banco</th><th>Emisor</th><th>Monto</th><th>Referencia</th><th>Comanda</th><th>Fecha Canje</th><th>IP Canje</th><th>Acciones</th></tr></thead><tbody>{% for p in pagos %}<tr>
<td><small>{{p[1]}}<br>{{p[2]}}</small></td>
<td><span class="badge badge-{{p[10]|lower}}">{{p[10]}}</span></td>
<td>{{p[3]}}</td>
<td style="font-weight:800;">Bs. {{p[4]}}</td>
<td><code>{{p[5]}}</code></td>
<td><b style="color:var(--primary)">{{p[9] if p[9] else '-'}}</b></td>
<td><small>{{p[7] if p[7] else '-'}}</small></td>
<td><small style="color:#888">{{p[11] if p[11] else '-'}}</small></td>
<td><div style="display:flex; gap:5px; justify-content:center;">
<form method="POST" action="/admin/eliminar" onsubmit="return confirm('¿Borrar definitivamente?');" style="display:flex; gap:2px;"><input type="hidden" name="ref" value="{{p[5]}}"><input type="password" name="pw" placeholder="PIN" style="width:40px; padding:5px; font-size:10px;"><button class="btn-danger" style="padding:5px 8px; border-radius:8px; border:none; cursor:pointer;">🗑️</button></form>
</div></td></tr>{% endfor %}</tbody></table></div><div class="grid-totales"><div class="total-item" style="background:linear-gradient(135deg,#D32F2F,#FF5252);">Bs. {{ totales.bs }}</div><div class="total-item" style="background:linear-gradient(135deg,#f3ba2f,#fdd835); color:#000;">$ {{ totales.usd }}</div><div class="total-item" style="background:linear-gradient(135deg,#007A33,#2E7D32);">{{ totales.cop }} COP</div></div></div><script>function f(){let v=document.getElementById("busc").value.toUpperCase(),t=document.getElementById("tab"),r=t.getElementsByTagName("tr");for(let i=1;i<r.length;i++){r[i].style.display=r[i].innerText.toUpperCase().includes(v)?"":"none"}}</script></body></html>'''

# --- RUTAS ---
@app.route('/')
def index(): return render_template_string(HTML_PORTAL)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form.get('password') == os.getenv("ADMIN_PASSWORD"):
        session['logged_in'] = True; return redirect(url_for('admin'))
    return render_template_string(HTML_LOGIN)

@app.route('/admin')
def admin():
    if not session.get('logged_in'): return redirect(url_for('login'))
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT id, fecha_recepcion, hora_recepcion, emisor, monto, referencia, mensaje_completo, fecha_canje, estado, comanda, banco, ip_canje FROM pagos ORDER BY id DESC")
    pagos = cur.fetchall()
    t_bs, t_usd, t_cop = 0.0, 0.0, 0.0
    for p in pagos:
        try:
            m, b = str(p[4]), p[10]
            val = float(m.replace('.','').replace(',','.')) if ',' in m else float(m)
            if b == 'BINANCE': t_usd += val
            elif b in ['NEQUI','BANCOLOMBIA']: t_cop += val
            else: t_bs += val
        except: continue
    totales = {"bs": f"{t_bs:,.2f}", "usd": f"{t_usd:,.2f}", "cop": f"{t_cop:,.0f}"}
    conn.close(); return render_template_string(HTML_ADMIN, pagos=pagos, totales=totales)

@app.route('/verificar', methods=['POST'])
def verificar():
    ref = request.form.get('ref', '').strip()
    com_ingresada = request.form.get('comanda', '').strip()
    
    # Capturar IP e ID de tiempo en Venezuela (VET)
    user_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    fecha_accion = datetime.now(VET).strftime("%d/%m/%Y %I:%M %p")
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT id, estado, banco, monto, referencia FROM pagos WHERE referencia = %s", (ref,))
    pago = cur.fetchone()
    res = {"titulo": "ERROR", "mensaje": "Referencia no encontrada.", "clase": "error"}
    
    if pago:
        if pago[1] == 'LIBRE':
            cur.execute("""
                UPDATE pagos 
                SET estado = 'CANJEADO', comanda = %s, fecha_canje = %s, ip_canje = %s 
                WHERE id = %s
            """, (com_ingresada, fecha_accion, user_ip, pago[0]))
            conn.commit()
            res = {"titulo": "PAGO VALIDADO", "mensaje": "Comprobante vinculado exitosamente.", "clase": "success", "datos": {"banco": pago[2], "monto": pago[3], "ref": pago[4], "comanda": com_ingresada, "fecha": fecha_accion, "ip": user_ip}}
        else:
            res = {"titulo": "PAGO YA USADO", "mensaje": "Esta referencia ya fue canjeada anteriormente.", "clase": "error"}
    conn.close(); return render_template_string(HTML_PORTAL, resultado=res)

@app.route('/admin/eliminar', methods=['POST'])
def eliminar():
    if session.get('logged_in') and request.form.get('pw') == os.getenv("ADMIN_PASSWORD"):
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("DELETE FROM pagos WHERE referencia = %s", (request.form.get('ref'),))
        conn.commit(); conn.close()
    return redirect(url_for('admin'))

@app.route('/admin/exportar')
def exportar():
    conn = get_db_connection(); df = pd.read_sql("SELECT * FROM pagos", conn); conn.close()
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as writer: df.to_excel(writer, index=False)
    out.seek(0); return send_file(out, as_attachment=True, download_name="reporte_sistemas_mv.xlsx")

@app.route('/webhook-bdv', methods=['POST'])
def webhook():
    try:
        raw_data = request.get_json(silent=True) or {"mensaje": request.get_data(as_text=True)}
        texto = str(raw_data.get('mensaje', ''))
        pagos = extractor_inteligente(texto)
        if pagos:
            conn = get_db_connection(); cur = conn.cursor()
            ahora_vet = datetime.now(VET)
            for p in pagos:
                cur.execute("SELECT 1 FROM pagos WHERE referencia = %s", (p['referencia'],))
                if not cur.fetchone():
                    cur.execute("""
                        INSERT INTO pagos (fecha_recepcion, hora_recepcion, emisor, monto, referencia, mensaje_completo, estado, banco) 
                        VALUES (%s, %s, %s, %s, %s, %s, 'LIBRE', %s)
                    """, (ahora_vet.strftime("%d/%m/%Y"), ahora_vet.strftime("%I:%M %p"), p['emisor'], p['monto'], p['referencia'], p['original'], p['banco']))
            conn.commit(); conn.close()
        return "OK", 200
    except: return "OK", 200

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)