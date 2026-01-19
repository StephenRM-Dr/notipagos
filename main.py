import psycopg2
import re
import os
import pandas as pd
from flask import Flask, request, render_template_string, redirect, url_for, session, send_file
from datetime import datetime
from io import BytesIO
from dotenv import load_dotenv

# --- CONFIGURACIÓN ---
load_dotenv(override=True)
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "clave_sistemas_mv_2026")

# --- BASE DE DATOS ---
def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        port=os.getenv("DB_PORT", "5432"),
        sslmode="require" if "neon.tech" in (os.getenv("DB_HOST") or "") else "disable"
    )

# --- EXTRACTOR INTELIGENTE (Todos los Bancos + Sofitasa) ---
def extractor_inteligente(texto):
    # El programa usa un limpiador de texto
    texto_limpio = texto.replace('"', '').replace('\\n', ' ').replace('\n', ' ').strip()
    pagos_detectados = []
    
    patrones = {
        "BDV": (
            r"BDV|PagomovilBDV", 
            r"(?:del|tlf|desde el tlf)\s*(\d{4}-\d+|\d{10,11})", 
            r"(?:por|Bs\.?|Monto:)\s*([\d.]+,\d{2})", 
            r"Ref:\s*(\d+)"
        ),
        "BANESCO": (
            r"Banesco", 
            r"(?:de|desde|tlf)\s*(\d{10,11})", 
            r"(?:Bs\.?|Monto:?\s*Bs\.?|por)\s*([\d.]+,\d{2})", 
            r"Ref:\s*(\d+)"
        ),
        "SOFITASA": (
            r"Sofitasa", 
            r"(?:de|desde|del tlf)\s*(\d{10,11})", 
            r"(?:Bs\.?|por)\s*([\d.]+,\d{2})", 
            r"(?:Ref:|Referencia:)\s*(\d+)"
        ),
        "BINANCE": (
            r"Binance", 
            r"(?:from|de)\s+(.*?)\s+(?:received|el)", 
            r"([\d.]+)\s*USDT", 
            r"(?:ID|Order):\s*(\d+)"
        ),
        "BANCOLOMBIA": (
            r"Bancolombia", 
            r"en\s+(.*?)\s+por", 
            r"\$\s*([\d.]+)", 
            r"Ref\.\s*(\d+)"
        ),
        "NEQUI": (
            r"Nequi", 
            r"De\s+(.*?)\s?te", 
            r"\$\s*([\d.]+)", 
            r"referencia\s*(\d+)"
        ),
        "PLAZA": (
            r"Plaza", 
            r"desde\s+(.*?)\s+por", 
            r"Bs\.\s*([\d.]+,\d{2})", 
            r"Ref:\s*(\d+)"
        )
    }

    for banco, (key, re_emi, re_mon, re_ref) in patrones.items():
        if re.search(key, texto_limpio, re.IGNORECASE):
            m_emi = re.search(re_emi, texto_limpio, re.IGNORECASE)
            m_mon = re.search(re_mon, texto_limpio, re.IGNORECASE)
            m_ref = re.search(re_ref, texto_limpio, re.IGNORECASE)
            if m_ref:
                pagos_detectados.append({
                    "banco": banco, 
                    "emisor": m_emi.group(1) if m_emi else "S/D", 
                    "monto": m_mon.group(1) if m_mon else "0,00", 
                    "referencia": m_ref.group(1)
                })
    return pagos_detectados

# --- CSS DEFINITIVO (Responsivo y Colores por Banco) ---
CSS_FINAL = '''
:root { 
    --primary: #004481; --secondary: #f4f7f9; --danger: #d9534f; --success: #28a745; --warning: #ffc107;
    --bdv: #D32F2F; --banesco: #007A33; --binance: #F3BA2F; --colombia: #FDB813; --plaza: #005691; --sofitasa: #0097A7;
}
* { box-sizing: border-box; }
body { font-family: 'Segoe UI', sans-serif; background: var(--secondary); margin: 0; }
.container { width: 100%; max-width: 1200px; margin: auto; padding: 15px; }
.logo-main { max-width: 180px; height: auto; display: block; margin: 0 auto 20px auto; }
.card { background: white; border-radius: 15px; box-shadow: 0 8px 20px rgba(0,0,0,0.06); padding: 25px; margin-bottom: 20px; border: 1px solid rgba(0,0,0,0.05); }
.btn { border: none; border-radius: 10px; padding: 12px 20px; font-weight: 600; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; gap: 8px; transition: 0.3s; justify-content: center; }
.btn-primary { background: var(--primary); color: white; }
.btn-light { background: #fff; color: #555; border: 1px solid #ddd; }
.badge { padding: 6px 12px; border-radius: 20px; font-weight: bold; font-size: 10px; text-transform: uppercase; color: white; display: inline-block; }
.badge-bdv { background-color: var(--bdv); }
.badge-banesco { background-color: var(--banesco); }
.badge-binance { background-color: var(--binance); color: #000; }
.badge-bancolombia, .badge-nequi { background-color: var(--colombia); color: #000; }
.badge-sofitasa { background-color: var(--sofitasa); }
.table-wrapper { overflow-x: auto; background: white; border-radius: 15px; }
table { width: 100%; border-collapse: collapse; min-width: 900px; }
th { background: #fcfcfc; padding: 18px; text-align: left; font-size: 11px; color: #888; border-bottom: 2px solid #eee; }
tr:hover { background-color: #f9fbff; }
td { padding: 16px; border-bottom: 1px solid #f1f1f1; font-size: 14px; }
.grid-totales { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 20px; margin-top: 20px; }
.total-item { padding: 25px; border-radius: 18px; color: white; font-weight: bold; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
#loader { display: none; border: 3px solid #f3f3f3; border-top: 3px solid var(--primary); border-radius: 50%; width: 25px; height: 25px; animation: spin 1s linear infinite; margin: 10px auto; }
@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
@media (max-width: 600px) { .nav-header { flex-direction: column; gap:10px; } .btn { width: 100%; } }
'''

# --- VISTAS HTML ---
HTML_PORTAL = '''<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verificador</title><style>''' + CSS_FINAL + '''</style></head><body>
<div class="container" style="max-width:480px; margin-top:30px;">
    <div style="display:flex; justify-content:space-between; margin-bottom:20px;" class="nav-header">
        <a href="/" class="btn btn-light">🔄 Refrescar</a>
        <a href="/admin" class="btn btn-primary">⚙️ Admin</a>
    </div>
    <div class="card" style="text-align:center;">
        <img src="{{ logo_url }}" class="logo-main" alt="Logo">
        <h2 style="color:var(--primary);">Verificar Pago</h2>
        <form id="verifyForm" method="POST" action="/verificar">
            <input type="text" name="ref" placeholder="Referencia" style="width:100%; padding:18px; font-size:20px; border:2px solid #eee; border-radius:12px; text-align:center; margin-bottom:20px;" required autocomplete="off">
            <button type="submit" class="btn btn-primary" style="width:100%; padding:18px;">CONSULTAR</button>
        </form>
        <div id="loader"></div>
        {% if resultado %}
        <div style="margin-top:25px; padding:20px; border-radius:15px; text-align:left; border-left: 5px solid;" class="{{ resultado.clase }}">
            <h3>{{ resultado.mensaje }}</h3>
            {% if resultado.datos %}<p><b>De:</b> {{ resultado.datos[0] }}<br><b>Monto:</b> {{ resultado.datos[1] }}<br><b>Ref:</b> {{ resultado.datos[3] }}</p>{% endif %}
        </div>
        <audio autoplay><source src="{{ 'https://assets.mixkit.co/active_storage/sfx/2000/2000-preview.mp3' if resultado.clase == 'success' else 'https://assets.mixkit.co/active_storage/sfx/2014/2014-preview.mp3' }}" type="audio/mpeg"></audio>
        {% endif %}
    </div>
</div>
<script>document.getElementById('verifyForm').onsubmit = function(){ document.getElementById('loader').style.display='block'; };</script>
</body></html>'''

HTML_ADMIN = '''<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Admin</title><style>''' + CSS_FINAL + '''</style></head><body>
<div class="container">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:30px; flex-wrap:wrap; gap:15px;">
        <img src="{{ logo_url }}" height="55">
        <div style="display:flex; gap:10px;">
            <a href="/" class="btn btn-light">🔍 Verificador</a>
            <a href="/admin/exportar" class="btn btn-primary" style="background:#28a745;">📊 Excel</a>
            <a href="/logout" class="btn btn-danger">Salir</a>
        </div>
    </div>
    <div class="card" style="padding:15px;"><input type="text" id="adminSearch" placeholder="🔍 Buscar pago..." onkeyup="filterTable()" style="width:100%; padding:15px; border-radius:10px; border:1px solid #ddd; outline:none;"></div>
    <div class="table-wrapper card" style="padding:0;">
        <table id="paymentsTable">
            <thead><tr><th>Fecha/Hora</th><th>Banco</th><th>Emisor</th><th>Monto</th><th>Ref</th><th>Estado</th><th>Acciones</th></tr></thead>
            <tbody>{% for p in pagos %}
            <tr>
                <td>{{p[1]}}<br><small style="color:#999;">{{p[2]}}</small></td>
                <td><span class="badge badge-{{p[9]|lower}}">{{p[9]}}</span></td>
                <td>{{p[3]}}</td>
                <td style="font-weight:700;">
                    {% if p[9] == 'BINANCE' %}$ {{p[4]}}
                    {% elif p[9] in ['NEQUI','BANCOLOMBIA'] %}{{p[4]}} COP
                    {% else %}Bs. {{p[4]}}{% endif %}
                </td>
                <td><code>{{p[5]}}</code></td>
                <td><span class="badge" style="color:{% if p[7]=='LIBRE' %}#1a7f37{% else %}#af1f2c{% endif %}; background:{% if p[7]=='LIBRE' %}#dcffe4{% else %}#ffdce0{% endif %};">{{p[7]}}</span></td>
                <td>{% if p[7] == 'CANJEADO' %}
                    <form method="POST" action="/admin/liberar" style="display:flex; gap:3px;">
                        <input type="hidden" name="ref" value="{{p[5]}}">
                        <input type="password" name="pw" placeholder="PIN" style="width:50px; border-radius:6px; border:1px solid #ddd;" required>
                        <button type="submit" class="btn btn-warning" style="padding:5px;">Reset</button>
                    </form>{% endif %}
                </td>
            </tr>{% endfor %}</tbody>
        </table>
    </div>
    <div class="grid-totales">
        <div class="total-item" style="background: linear-gradient(135deg, #D32F2F, #FF5252);">Bs. {{ totales.bs }}</div>
        <div class="total-item" style="background: linear-gradient(135deg, #f3ba2f, #fdd835); color:#000;">$ {{ totales.usd }}</div>
        <div class="total-item" style="background: linear-gradient(135deg, #007A33, #2E7D32);">{{ totales.cop }} COP</div>
    </div>
</div>
<script>function filterTable() { let input = document.getElementById("adminSearch").value.toUpperCase(); let rows = document.getElementById("paymentsTable").getElementsByTagName("tr"); for (let i = 1; i < rows.length; i++) { rows[i].style.display = rows[i].textContent.toUpperCase().includes(input) ? "" : "none"; } }</script>
</body></html>'''

# --- RUTAS ---
@app.route('/')
def index(): return render_template_string(HTML_PORTAL, logo_url=url_for('static', filename='logo.png'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form.get('password') == os.getenv("ADMIN_PASSWORD", "admin123"):
        session['logged_in'] = True; return redirect(url_for('admin'))
    return render_template_string('<body style="display:flex; justify-content:center; align-items:center; height:100vh; background:#f4f7f9;"><form method="POST" style="background:white; padding:40px; border-radius:15px;"><input type="password" name="password" placeholder="Admin PIN" style="padding:15px; border-radius:10px; border:1px solid #ddd; width:100%; margin-bottom:15px;"><button type="submit" class="btn btn-primary" style="width:100%;">ENTRAR</button></form></body>')

@app.route('/admin')
def admin():
    if not session.get('logged_in'): return redirect(url_for('login'))
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT * FROM pagos ORDER BY id DESC")
    pagos = cursor.fetchall()
    
    # Cálculo de totales por moneda
    t_bs, t_usd, t_cop = 0.0, 0.0, 0.0
    for p in pagos:
        try:
            m, b = str(p[4]), p[9]
            if b == 'BINANCE': t_usd += float(m)
            elif b in ['NEQUI','BANCOLOMBIA']: t_cop += float(m.replace('.',''))
            else: t_bs += float(m.replace('.','').replace(',','.'))
        except: continue
    totales = {"bs": f"{t_bs:,.2f}", "usd": f"{t_usd:,.2f}", "cop": f"{t_cop:,.0f}"}
    conn.close(); return render_template_string(HTML_ADMIN, pagos=pagos, totales=totales, logo_url=url_for('static', filename='logo.png'))

@app.route('/verificar', methods=['POST'])
def verificar():
    ref = request.form.get('ref', '').strip()
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT id, emisor, monto, estado, referencia FROM pagos WHERE referencia LIKE %s LIMIT 1", ('%' + ref,))
    pago = cursor.fetchone()
    if not pago: res = {"clase": "danger", "mensaje": "❌ NO ENCONTRADO"}
    elif pago[3] == 'CANJEADO': res = {"clase": "warning", "mensaje": "⚠️ YA CANJEADO", "datos": pago[1:]}
    else:
        cursor.execute("UPDATE pagos SET estado = 'CANJEADO', fecha_canje = %s WHERE id = %s", (datetime.now().strftime("%d/%m %H:%M"), pago[0]))
        conn.commit(); res = {"clase": "success", "mensaje": "✅ VÁLIDO", "datos": pago[1:]}
    conn.close(); return render_template_string(HTML_PORTAL, resultado=res, logo_url=url_for('static', filename='logo.png'))

@app.route('/admin/liberar', methods=['POST'])
def liberar():
    if session.get('logged_in') and request.form.get('pw') == os.getenv("ADMIN_PASSWORD"):
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("UPDATE pagos SET estado = 'LIBRE', fecha_canje = NULL WHERE referencia = %s", (request.form.get('ref'),))
        conn.commit(); conn.close()
    return redirect(url_for('admin'))

@app.route('/admin/exportar')
def exportar():
    if not session.get('logged_in'): return redirect(url_for('login'))
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT fecha_recepcion, banco, emisor, monto, referencia, estado FROM pagos")
    df = pd.DataFrame(cursor.fetchall(), columns=['Fecha', 'Banco', 'Emisor', 'Monto', 'Ref', 'Estado'])
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as writer: df.to_excel(writer, index=False)
    out.seek(0)
    return send_file(out, as_attachment=True, download_name="Reporte_General.xlsx")

@app.route('/webhook-bdv', methods=['POST'])
def webhook():
    try:
        raw_data = request.get_json(silent=True) or {"mensaje": request.get_data(as_text=True)}
        lista_pagos = extractor_inteligente(str(raw_data.get('mensaje', '')))
        conn = get_db_connection(); cursor = conn.cursor()
        for p in lista_pagos:
            cursor.execute("SELECT 1 FROM pagos WHERE referencia = %s", (p['referencia'],))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO pagos (fecha_recepcion, hora_recepcion, emisor, monto, referencia, banco) VALUES (%s, %s, %s, %s, %s, %s)", 
                               (datetime.now().strftime("%d/%m/%Y"), datetime.now().strftime("%I:%M %p"), p['emisor'], p['monto'], p['referencia'], p['banco']))
        conn.commit(); conn.close(); return "OK", 200
    except Exception as e: return str(e), 200

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)