import psycopg2
import re
import json
import os
import pandas as pd
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session, send_file, make_response
from datetime import datetime, timedelta
from io import BytesIO
from dotenv import load_dotenv

# --- CARGAR CONFIGURACIÓN ---
load_dotenv(override=True)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "clave_sistemas_mv_2026")

# Seguridad de sesión
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30)
)

# --- CONFIGURACIÓN DE BASE DE DATOS ---
def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        port=os.getenv("DB_PORT", "5432"),
        sslmode="require" if "neon.tech" in (os.getenv("DB_HOST") or "") else "disable",
        client_encoding='utf8'
    )

def inicializar_db():
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pagos (
                id SERIAL PRIMARY KEY,
                fecha_recepcion VARCHAR(20),
                hora_recepcion VARCHAR(20),
                emisor VARCHAR(255),
                monto VARCHAR(50),
                referencia VARCHAR(100) UNIQUE, 
                mensaje_completo TEXT,
                estado VARCHAR(20) DEFAULT 'LIBRE',
                fecha_canje TEXT,
                banco VARCHAR(50) DEFAULT 'BDV'
            )
        ''')
        cursor.execute('''
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pagos' AND column_name='banco') THEN
                    ALTER TABLE pagos ADD COLUMN banco VARCHAR(50) DEFAULT 'BDV';
                END IF;
            END $$;
        ''')
        conn.commit(); cursor.close(); conn.close()
        print("✅ Base de Datos operativa.")
    except Exception as e: print(f"❌ Error DB: {e}")

# --- LÓGICA DE EXTRACCIÓN UNIVERSAL (SMS + NOTIFICACIONES) ---
def extractor_inteligente(texto):
    texto_limpio = texto.replace('"', '').replace('\\n', ' ').replace('\n', ' ').strip()
    pagos_detectados = []
    
    patrones = {
        "BDV": (r"BDV", r"(?:desde el tlf|de)\s+(\d+)", r"por\s+([\d.]+,\d{2})\s+Bs", r"Ref:\s?(\d+)"),
        "BANESCO": (r"Banesco", r"(?:de|desde)\s+(\d+)", r"Bs\.\s?([\d.]+,\d{2})", r"Ref:\s?(\d+)"),
        "BINANCE": (r"Binance", r"(?:from|de)\s+(.*?)\s+(?:received|el)", r"([\d.]+)\s?USDT", r"(?:ID|Order):\s?(\d+)"),
        "BANCOLOMBIA": (r"Bancolombia", r"en\s+(.*?)\s+por", r"\$\s?([\d.]+)", r"Ref\.\s?(\d+)"),
        "NEQUI": (r"Nequi", r"De\s+(.*?)\s?te", r"\$\s?([\d.]+)", r"referencia\s?(\d+)"),
        "PLAZA": (r"Plaza", r"desde\s+(.*?)\s+por", r"Bs\.\s?([\d.]+,\d{2})", r"Ref:\s?(\d+)|R\.\.\.\s?(\d+)")
    }

    for banco, (key, re_emi, re_mon, re_ref) in patrones.items():
        if re.search(key, texto_limpio, re.IGNORECASE):
            emisores = re.findall(re_emi, texto_limpio, re.IGNORECASE)
            montos = re.findall(re_mon, texto_limpio, re.IGNORECASE)
            refs_raw = re.findall(re_ref, texto_limpio, re.IGNORECASE)
            
            for i in range(len(refs_raw)):
                actual_ref = refs_raw[i]
                if isinstance(actual_ref, tuple):
                    actual_ref = next((x for x in actual_ref if x), None)

                pagos_detectados.append({
                    "banco": banco,
                    "emisor": emisores[i].strip() if i < len(emisores) else "Remitente Desconocido",
                    "monto": montos[i] if i < len(montos) else "0,00",
                    "referencia": actual_ref
                })
    return pagos_detectados
# --- ESTILOS CSS ---
CSS_COMUN = '''
:root { --primary: #004481; --secondary: #f4f7f9; --accent: #00b1ea; --danger: #d9534f; --success: #28a745; --warning: #ffc107; }
body { font-family: 'Segoe UI', Arial, sans-serif; background-color: var(--secondary); margin: 0; color: #333; line-height: 1.5; }
.wrapper, .container { width: 100%; max-width: 1150px; margin: auto; padding: 10px; box-sizing: border-box; }
.btn { border: none; border-radius: 8px; padding: 10px 15px; font-weight: 600; cursor: pointer; transition: 0.3s; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; font-size: 14px; gap: 5px; }
.btn-primary { background: var(--primary); color: white; }
.btn-success { background: var(--success); color: white; }
.btn-danger { background: var(--danger); color: white; }
.card { background: white; border-radius: 15px; box-shadow: 0 5px 15px rgba(0,0,0,0.05); padding: 20px; border: 1px solid #eee; margin-bottom: 20px; }
.table-container { overflow-x: auto; border-radius: 12px; border: 1px solid #eee; }
table { width: 100%; border-collapse: collapse; min-width: 900px; }
th { background: #f8f9fa; color: #555; padding: 15px; border-bottom: 2px solid #eee; text-align: left; font-size: 11px; text-transform: uppercase; }
td { padding: 12px; border-bottom: 1px solid #eee; font-size: 14px; }
.badge { padding: 4px 10px; border-radius: 50px; font-size: 10px; font-weight: bold; }
.LIBRE { background: #e7f4e8; color: #2e7d32; }
.CANJEADO { background: #fdecea; color: #c62828; }
.badge-banco { padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: bold; }
.badge-bdv { background: #ffebee; color: #c62828; }
.badge-binance { background: #fffde7; color: #856404; border: 1px solid #ffeeba; }
.resumen-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; margin-top: 25px; }
.resumen-card { background: white; padding: 20px; border-radius: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border-left: 5px solid var(--primary); }
'''

# --- VISTAS HTML ---
HTML_LOGIN = '''<!DOCTYPE html><html><head><title>Login</title><style>''' + CSS_COMUN + '''body{display:flex;justify-content:center;align-items:center;height:100vh;background:#004481;}</style></head><body><div class="card" style="width:350px;text-align:center;"><h3>Acceso Administrativo</h3><form method="POST"><input type="password" name="password" placeholder="Clave" style="width:100%;padding:12px;margin-bottom:15px;border:1px solid #ddd;border-radius:8px;box-sizing:border-box;" required autofocus><button type="submit" class="btn btn-primary" style="width:100%;">ENTRAR</button></form></div></body></html>'''
HTML_PORTAL = '''<!DOCTYPE html><html><head><title>Verificador</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>''' + CSS_COMUN + '''</style></head><body><div class="wrapper"><div style="display:flex;justify-content:space-between;margin-bottom:20px;"><a href="/" class="btn" style="background:#ddd;">🔄 Limpiar</a><a href="/admin" class="btn btn-primary">⚙️ Admin</a></div><div class="card" style="text-align:center;"><h2>Verificar Referencia</h2><form method="POST" action="/verificar"><input type="text" name="ref" placeholder="Ej: 123456" style="width:100%;padding:15px;font-size:24px;border:2px solid #eee;border-radius:12px;text-align:center;margin-bottom:15px;box-sizing:border-box;" required autocomplete="off"><button type="submit" class="btn btn-primary" style="width:100%;padding:15px;font-size:18px;">CONSULTAR PAGO</button></form>{% if resultado %}<div style="margin-top:20px;padding:20px;border-radius:10px;" class="{{ resultado.clase }}"><h3>{{ resultado.mensaje }}</h3>{% if resultado.datos %}<b>Emisor:</b> {{ resultado.datos[0] }}<br><b>Monto:</b> {{ resultado.datos[1] }}<br><b>Ref:</b> {{ resultado.datos[3] }}{% endif %}</div>{% endif %}</div></div></body></html>'''
HTML_ADMIN = '''<!DOCTYPE html><html><head><title>Admin Panel</title><style>''' + CSS_COMUN + '''</style></head><body><div class="container"><div class="header-admin" style="display:flex;justify-content:space-between;align-items:center;margin-top:20px;"><h2>Gestión de Pagos</h2><div><a href="/admin/exportar" class="btn btn-success">Excel</a><a href="/logout" class="btn btn-danger">Salir</a></div></div><form method="GET" style="display:flex;gap:10px;margin:20px 0;"><input type="text" name="q" placeholder="Buscar..." class="btn" style="background:white;border:1px solid #ddd;flex-grow:1;" value="{{ query }}"><button type="submit" class="btn btn-primary">Filtrar</button></form><div class="table-container"><table><thead><tr><th>Fecha/Hora</th><th>Banco</th><th>Emisor</th><th>Monto</th><th>Referencia</th><th>Estado</th></tr></thead><tbody>{% for p in pagos %}<tr><td>{{p[1]}}<br><small>{{p[2]}}</small></td><td><span class="badge-banco badge-{{p[9]|lower}}">{{p[9]}}</span></td><td>{{p[3]}}</td><td style="font-weight:bold;">{{p[4]}}</td><td><code>{{p[5]}}</code></td><td><span class="badge {{p[7]}}">{{p[7]}}</span></td></tr>{% endfor %}</tbody></table></div><div class="resumen-grid"><div class="resumen-card"><small>TOTAL BS</small><b>Bs. {{ totales.bs }}</b></div><div class="resumen-card"><small>TOTAL BINANCE</small><b>$ {{ totales.usd }}</b></div><div class="resumen-card"><small>TOTAL COP</small><b>$ {{ totales.cop }}</b></div></div></div></body></html>'''

# --- RUTAS ---
@app.route('/')
def index(): return render_template_string(HTML_PORTAL)

@app.route('/webhook-bdv', methods=['POST'])
def webhook():
    try:
        raw_data = request.get_json(silent=True) or {"mensaje": request.get_data(as_text=True)}
        texto = raw_data.get('mensaje', '')
        lista_pagos = extractor_inteligente(texto)
        if not lista_pagos: return "No detectado", 200
        conn = get_db_connection(); cursor = conn.cursor()
        for p in lista_pagos:
            cursor.execute("SELECT 1 FROM pagos WHERE referencia = %s", (p['referencia'],))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO pagos (fecha_recepcion, hora_recepcion, emisor, monto, referencia, banco) VALUES (TO_CHAR(CURRENT_DATE, 'DD/MM/YYYY'), TO_CHAR(NOW(), 'HH12:MI AM'), %s, %s, %s, %s)", (p['emisor'], p['monto'], p['referencia'], p['banco']))
        conn.commit(); cursor.close(); conn.close()
        return "OK", 200
    except Exception as e: return str(e), 200

@app.route('/verificar', methods=['POST'])
def verificar():
    ref = request.form.get('ref', '').strip()
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT id, emisor, monto, estado, referencia FROM pagos WHERE referencia LIKE %s LIMIT 1 FOR UPDATE", ('%' + ref,))
    pago = cursor.fetchone()
    if not pago: res = {"clase": "danger", "mensaje": "❌ NO ENCONTRADO"}
    elif pago[3] == 'CANJEADO': res = {"clase": "warning", "mensaje": "⚠️ YA USADO", "datos": pago[1:]}
    else:
        cursor.execute("UPDATE pagos SET estado = 'CANJEADO', fecha_canje = %s WHERE id = %s", (datetime.now().strftime("%d/%m/%Y %H:%M"), pago[0]))
        conn.commit(); res = {"clase": "success", "mensaje": "✅ VÁLIDO", "datos": pago[1:]}
    conn.close(); return render_template_string(HTML_PORTAL, resultado=res)

@app.route('/admin')
def admin():
    if not session.get('logged_in'): return redirect(url_for('login'))
    q = request.args.get('q', '').strip()
    conn = get_db_connection(); cursor = conn.cursor()
    sql = "SELECT * FROM pagos WHERE emisor ILIKE %s OR referencia LIKE %s ORDER BY id DESC"
    cursor.execute(sql, (f"%{q}%", f"%{q}%"))
    pagos = cursor.fetchall()
    
    t_bs, t_usd, t_cop = 0.0, 0.0, 0.0
    for p in pagos:
        try:
            m_str, banco = str(p[4]), p[9]
            if banco == 'BINANCE': t_usd += float(m_str)
            elif banco in ['BANCOLOMBIA', 'NEQUI']: t_cop += float(m_str.replace('.', ''))
            else: t_bs += float(m_str.replace('.', '').replace(',', '.'))
        except: continue

    totales = {"bs": f"{t_bs:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), "usd": f"{t_usd:,.2f}", "cop": f"{t_cop:,.0f}"}
    cursor.close(); conn.close()
    return render_template_string(HTML_ADMIN, pagos=pagos, totales=totales, query=q)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == os.getenv("ADMIN_PASSWORD", "admin123"):
            session['logged_in'] = True
            return redirect(url_for('admin'))
    return render_template_string(HTML_LOGIN)

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

@app.route('/admin/exportar')
def exportar():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT * FROM pagos")
    df = pd.DataFrame(cursor.fetchall())
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w: df.to_excel(w)
    out.seek(0); return send_file(out, as_attachment=True, download_name="reporte.xlsx")

if __name__ == '__main__':
    inicializar_db()
    app.run(host='0.0.0.0', port=5000)