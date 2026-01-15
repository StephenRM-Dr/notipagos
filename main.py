import sqlite3
import re
import json
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)
DB_NAME = "pagos_bdv.db"

def limpiar_mensaje_bdv(texto):
    # Quitamos comillas y limpiamos espacios extraños
    texto_limpio = texto.replace('"', '').replace('\n', ' ').strip()
    
    # 1. Regex para Emisor
    regex_emisor = r"de\s+(.*?)\s+por"
    
    # 2. Regex para Monto (Soporta Bs. o Bs)
    regex_monto = r"Bs\.?\s?([\d.]+,\d{2})"
    
    # 3. Regex para Referencia (MEJORADO)
    # Busca cualquier número largo (8 a 15 dígitos) que aparezca al final 
    # o después de la palabra "operación" (con o sin acento)
    regex_ref = r"(?:operaci[óo]n\s+)(\d+)"

    emisor = re.search(regex_emisor, texto_limpio)
    monto = re.search(regex_monto, texto_limpio)
    ref = re.search(regex_ref, texto_limpio)

    # Si el regex específico falla, intentamos buscar cualquier número largo al final
    referencia_final = "No encontrada"
    if ref:
        referencia_final = ref.group(1)
    else:
        # Busca el último grupo de números de al menos 6 dígitos en el texto
        numeros_largos = re.findall(r"\d{6,}", texto_limpio)
        if numeros_largos:
            referencia_final = numeros_largos[-1]

    return {
        "emisor": emisor.group(1).strip() if emisor else "Desconocido",
        "monto": monto.group(1) if monto else "0,00",
        "referencia": referencia_final
    }
@app.route('/webhook-bdv', methods=['POST'])
def webhook():
    try:
        # Obtenemos el texto crudo
        raw_data = request.get_data(as_text=True).strip()
        
        # EL TRUCO: Si el mensaje tiene comillas internas mal formadas (""texto""), 
        # las convertimos en una sola para que el JSON sea válido.
        raw_data = raw_data.replace('""', '"')
        
        # Quitamos corchetes o comas accidentales al final
        raw_data = raw_data.strip().rstrip(',')

        data = json.loads(raw_data)
        mensaje = data.get("mensaje", "")
        
        if not mensaje or "{not_text_big}" in mensaje:
            return jsonify({"status": "ignored"}), 200

        datos = limpiar_mensaje_bdv(mensaje)
        
        ahora = datetime.now()
        fecha_hoy = ahora.strftime("%d/%m/%Y")
        hora_hoy = ahora.strftime("%I:%M:%S %p")

        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO pagos (fecha_recepcion, hora_recepcion, emisor, monto, referencia, mensaje_completo) 
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (fecha_hoy, hora_hoy, datos['emisor'], datos['monto'], datos['referencia'], mensaje))
            conn.commit()

        print(f"\n✅ REGISTRO EXITOSO: {hora_hoy}")
        print(f"👤 CLIENTE: {datos['emisor']}")
        print(f"💰 MONTO:   Bs. {datos['monto']}")
        print(f"🔢 REF:     {datos['referencia']}\n")
        
        return jsonify({"status": "success"}), 200

    except Exception as e:
        print(f"❌ Error de formato: {e}")
        # Si falla, imprimimos el contenido para ver exactamente qué comillas están estorbando
        print(f"Contenido recibido: [{request.get_data(as_text=True)}]")
        return jsonify({"status": "error"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)