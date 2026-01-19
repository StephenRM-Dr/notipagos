import psycopg2
import re
import os
import pandas as pd
from flask import Flask, request, render_template_string, redirect, url_for, session, send_file
from datetime import datetime, timedelta
from io import BytesIO
from dotenv import load_dotenv

# --- CONFIGURACIÓN ---
load_dotenv(override=True)
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "clave_sistemas_mv_2026")

# Branding
LOGO_URL = "https://imgur.com/a/w6jRX9S" 

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

# --- EXTRACTOR PROFESIONAL (Anti-Comisiones + Multibanco) ---
def extractor_inteligente(texto):
    # El programa usa un limpiador de texto
    texto_limpio = texto.replace('"', '').replace('\\n', ' ').replace('\n', ' ').strip()
    pagos_detectados = []
    
    patrones = {
        "BDV": (r"BDV|PagomovilBDV", r"(?:del|tlf|de)\s?(\d{4}-\d+)", r"por\s+Bs\.?\s?([\d.]+,\d{2})", r"Ref:\s?(\d+)"),
        "BANESCO": (r"Banesco", r"(?:de|desde)\s+(\d+)", r"Bs\.\s?([\d.]+,\d{2})", r"Ref:\s?(\d+)"),
        "BINANCE": (r"Binance", r"(?:from|de)\s+(.*?)\s+(?:received|el)", r"([\d.]+)\s?USDT", r"(?:ID|Order):\s?(\d+)"),
        "BANCOLOMBIA": (r"Bancolombia", r"en\s+(.*?)\s+por", r"\$\s?([\d.]+)", r"Ref\.\s?(\d+)"),
        "NEQUI": (r"Nequi", r"De\s+(.*?)\s?te", r"\$\s?([\d.]+)", r"referencia\s?(\d+)"),
        "PLAZA": (r"Plaza", r"desde\s+(.*?)\s+por", r"Bs\.\s?([\d.]+,\d{2})", r"Ref:\s?(\d+)")
    }

    for banco, (key, re_emi, re_mon, re_ref) in patrones.items():
        if re.search(key, texto_limpio, re.IGNORECASE):
            if banco == "BDV":
                m_emi = re.search(re_emi, texto_limpio, re.IGNORECASE)
                m_mon = re.search(re_mon, texto_limpio, re.IGNORECASE)
                m_ref = re.search(re_ref, texto_limpio, re.IGNORECASE)
                if m_ref:
                    pagos_detectados.append({"banco": banco, "emisor": m_emi.group(1) if m_emi else "S/D", "monto": m_mon.group(1) if m_mon else "0,00", "referencia": m_ref.group(1)})
            else:
                emisores = re.findall(re_emi, texto_limpio, re.IGNORECASE)
                montos = re.findall(re_mon, texto_limpio, re.IGNORECASE)
                refs = re.findall(re_ref, texto_limpio, re.IGNORECASE)
                for i in range(len(refs)):
                    actual_ref = refs[i] if not isinstance(refs[i], tuple) else next(x for x in refs[i] if x)
                    pagos_detectados.append({"banco": banco, "emisor": emisores[i] if i < len(emisores) else "S/D", "monto": montos[i] if i < len(montos) else "0,00", "referencia": actual_ref})
    return pagos_detectados

# --- ESTILOS MEJORADOS ---
CSS_FINAL = '''
:root { --primary: #004481; --secondary: #f4f7f9; --danger: #d9534f; --success: #28a745; --warning: #ffc107; }
body { font-family: 'Segoe UI', sans-serif; background: var(--secondary); margin: 0; }
.container { max-width: 1200px; margin: auto; padding: 20px; }
.card { background: white; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); padding: 20px; margin-bottom: 20px; }
.btn { border: none; border-radius: 6px; padding: 10px 15px; font-weight: bold; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; gap: 5px; font-size: 13px; }
.btn-primary { background: var(--primary); color: white; }
.btn-danger { background: var(--danger); color: white; }
.btn-warning { background: var(--warning); color: #333; }
.badge { padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 10px; }
.CANJEADO { background: #ffdce0; color: #af1f2c; }
.LIBRE { background: #dcffe4; color: #1a7f37; }
.badge-bdv { background: #ff000015; color: red; }
.badge-binance { background: #f3ba2f30; color: #856404; }
.grid-totales { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-top: 20px; }
.total-item { padding: 15px; border-radius: 10px; color: white; text-align: center; }
'''

# --- VISTA: PANEL ADMIN ---
HTML_ADMIN = '''<!DOCTYPE html><html><head><title>Admin</title><style>''' + CSS_FINAL + '''</style></head><body>
<div class="container">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
        <div style="display:flex; align-items:center; gap:15px;"><img src="''' + LOGO_URL + '''" height="50"><h2>Panel de Control</h2></div>
        <div>
            <a href="/" class="btn" style="background:#eee;">🔍 Verificador</a>
            <a href="/admin/exportar" class="btn btn-primary" style="background:#28a745;">📊 Excel</a>
            <a href="/logout" class="btn btn-danger">Salir</a>
        </div>
    </div>

    <div class="card" style="padding:0; overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse;">
            <thead><tr style="background:#f8f9fa;">
                <th style="padding:15px; text-align:left;">Recibido</th>
                <th>Banco</th><th>Emisor</th><th>Monto</th><th>Referencia</th><th>Estado / Canje</th><th>Acción</th>
            </tr></thead>
            <tbody>{% for p in pagos %}
            <tr style="border-bottom:1px solid #eee;">
                <td style="padding:15px;">{{p[1]}}<br><small style="color:#888;">{{p[2]}}</small></td>
                <td><span class="badge badge-{{p[9]|lower}}">{{p[9]}}</span></td>
                <td>{{p[3]}}</td>
                <td style="font-weight:bold;">
                    {% if p[9] == 'BINANCE' %}$ {{p[4]}}
                    {% elif p[9] in ['NEQUI','BANCOLOMBIA'] %}{{p[4]}} COP
                    {% else %}Bs. {{p[4]}}{% endif %}
                </td>
                <td><code>{{p[5]}}</code></td>
                <td>
                    <span class="badge {{p[7]}}">{{p[7]}}</span>
                    {% if p[8] %}<br><small style="font-size:9px; color:#666;">Canje: {{p[8]}}</small>{% endif %}
                </td>
                <td>
                    {% if p[7] == 'CANJEADO' %}
                    <form method="POST" action="/admin/liberar" style="display:flex; gap:3px;">
                        <input type="hidden" name="ref" value="{{p[5]}}">
                        <input type="password" name="pw" placeholder="PIN" style="width:45px; border:1px solid #ddd;" required>
                        <button type="submit" class="btn btn-warning" style="padding:4px 8px; font-size:10px;">Liberar</button>
                    </form>
                    {% endif %}
                </td>
            </tr>{% endfor %}</tbody>
        </table>
    </div>

    <div class="grid-totales">
        <div class="total-item" style="background:var(--primary);">
            <small>TOTAL BOLÍVARES</small><br><b style="font-size:20px;">Bs. {{ totales.bs }}</b>
        </div>
        <div class="total-item" style="background:#f3ba2f; color:#000;">
            <small>TOTAL BINANCE</small><br><b style="font-size:20px;">$ {{ totales.usd }}</b>
        </div>
        <div class="total-item" style="background:#e91e63;">
            <small>TOTAL COLOMBIA</small><br><b style="font-size:20px;">{{ totales.cop }} COP</b>
        </div>
    </div>
</div></body></html>'''

# --- VISTA: VERIFICADOR (CLIENTE) ---
HTML_PORTAL = '''<!DOCTYPE html><html><head><title>Verificar Pago</title><style>''' + CSS_FINAL + '''</style></head><body>
<div class="container" style="max-width:450px; margin-top:50px;">
    <div style="text-align:center; margin-bottom:20px;"><img src="''' + LOGO_URL + '''" width="180"></div>
    <div class="card" style="text-align:center;">
        <h2 style="color:var(--primary);">Verificar Referencia</h2>
        <form method="POST" action="/verificar">
            <input type="text" name="ref" placeholder="Ej: 0601..." style="width:100%; padding:15px; font-size:22px; border:2px solid #ddd; border-radius:10px; text-align:center; box-sizing:border-box;" required autocomplete="off" oninput="this.value = this.value.toUpperCase()">
            <br><br>
            <button type="submit" class="btn btn-primary" style="width:100%; padding:15px; font-size:18px; justify-content:center;">CONSULTAR PAGO</button>
        </form>
        {% if resultado %}
        <div style="margin-top:20px; padding:15px; border-radius:10px; text-align:left;" class="{{ resultado.clase }}">
            <h3 style="margin-top:0;">{{ resultado.mensaje }}</h3>
            {% if resultado.datos %}
            <div style="font-size:14px;">
                <b>👤 Emisor:</b> {{ resultado.datos[0] }}<br>
                <b>💰 Monto:</b> {{ resultado.datos[1] }}<br>
                <b>🔢 Ref:</b> {{ resultado.datos[3] }}
            </div>
            {% endif %}
        </div>
        {% endif %}
    </div>
</div></body></html>'''

# --- RUTAS ---
@app.route('/')
def index(): return render_template_string(HTML_PORTAL)

@app.route('/admin')
def admin():
    if not session.get('logged_in'): return redirect(url_for('login'))
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT * FROM pagos ORDER BY id DESC")
    pagos = cursor.fetchall()
    
    # Cálculo de totales
    t_bs, t_usd, t_cop = 0.0, 0.0, 0.0
    for p in pagos:
        try:
            m, b = str(p[4]), p[9]
            if b == 'BINANCE': t_usd += float(m)
            elif b in ['NEQUI','BANCOLOMBIA']: t_cop += float(m.replace('.',''))
            else: t_bs += float(m.replace('.','').replace(',','.'))
        except: continue
        
    totales = {"bs": f"{t_bs:,.2f}", "usd": f"{t_usd:,.2f}", "cop": f"{t_cop:,.0f}"}
    conn.close(); return render_template_string(HTML_ADMIN, pagos=pagos, totales=totales)

@app.route('/verificar', methods=['POST'])
def verificar():
    ref = request.form.get('ref', '').strip()
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT id, emisor, monto, estado, referencia FROM pagos WHERE referencia LIKE %s LIMIT 1", ('%' + ref,))
    pago = cursor.fetchone()
    if not pago: res = {"clase": "danger", "mensaje": "❌ PAGO NO ENCONTRADO"}
    elif pago[3] == 'CANJEADO': res = {"clase": "warning", "mensaje": "⚠️ YA FUE RECLAMADO", "datos": pago[1:]}
    else:
        cursor.execute("UPDATE pagos SET estado = 'CANJEADO', fecha_canje = %s WHERE id = %s", (datetime.now().strftime("%d/%m %H:%M"), pago[0]))
        conn.commit(); res = {"clase": "success", "mensaje": "✅ PAGO APROBADO", "datos": pago[1:]}
    conn.close(); return render_template_string(HTML_PORTAL, resultado=res)

@app.route('/admin/liberar', methods=['POST'])
def liberar():
    if session.get('logged_in') and request.form.get('pw') == os.getenv("ADMIN_PASSWORD"):
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("UPDATE pagos SET estado = 'LIBRE', fecha_canje = NULL WHERE referencia = %s", (request.form.get('ref'),))
        conn.commit(); conn.close()
    return redirect(url_for('admin'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form.get('password') == os.getenv("ADMIN_PASSWORD", "admin123"):
        session['logged_in'] = True; return redirect(url_for('admin'))
    return render_template_string('''<div style="text-align:center; margin-top:100px; font-family:sans-serif;">
        <form method="POST"><h2>Panel Admin</h2><input type="password" name="password" style="padding:10px;"><button type="submit" style="padding:10px;">Entrar</button></form></div>''')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/webhook-bdv', methods=['POST'])
def webhook():
    try:
        raw_data = request.get_json(silent=True) or {"mensaje": request.get_data(as_text=True)}
        texto = str(raw_data.get('mensaje', ''))
        lista_pagos = extractor_inteligente(texto)
        conn = get_db_connection(); cursor = conn.cursor()
        for p in lista_pagos:
            cursor.execute("SELECT 1 FROM pagos WHERE referencia = %s", (p['referencia'],))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO pagos (fecha_recepcion, hora_recepcion, emisor, monto, referencia, banco) VALUES (%s, %s, %s, %s, %s, %s)", 
                               (datetime.now().strftime("%d/%m/%Y"), datetime.now().strftime("%I:%M %p"), p['emisor'], p['monto'], p['referencia'], p['banco']))
        conn.commit(); conn.close(); return "OK", 200
    except Exception as e: return str(e), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)