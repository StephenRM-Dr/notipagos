import psycopg2
import os
from datetime import datetime
from dotenv import load_dotenv

def ejecutar_respaldo():
    # 1. Cargar configuración actualizada
    load_dotenv(override=True)
    
    db_host = os.getenv("DB_HOST")
    db_name = os.getenv("DB_NAME")
    db_user = os.getenv("DB_USER")
    db_pass = os.getenv("DB_PASS")
    db_port = os.getenv("DB_PORT", "5432")
    
    entorno = "NUBE ☁️" if "neon.tech" in db_host else "LOCAL 🏠"
    print(f"🚀 Iniciando respaldo desde: {entorno}...")

    try:
        # 2. Conectar a la base de datos
        conn = psycopg2.connect(
            host=db_host,
            database=db_name,
            user=db_user,
            password=db_pass,
            port=db_port,
            sslmode="require" if "neon.tech" in db_host else "disable"
        )
        cursor = conn.cursor()

        # 3. Obtener todos los registros de la tabla pagos
        cursor.execute("SELECT * FROM pagos")
        filas = cursor.fetchall()
        
        if not filas:
            print("⚠️ La tabla está vacía. No hay datos para respaldar.")
            return

        # 4. Crear el contenido del archivo SQL
        fecha_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        nombre_archivo = f"Backup_Pagos_{fecha_str}.sql"
        
        with open(nombre_archivo, "w", encoding="utf-8") as f:
            f.write(f"-- RESPALDO SISTEMA MV - {entorno}\n")
            f.write(f"-- FECHA: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
            f.write("-- -----------------------------------------------------\n\n")
            
            for r in filas:
                # Limpiar textos para evitar errores de comillas en SQL
                mensaje = r[6].replace("'", "''") if r[6] else ""
                fecha_canje = f"'{r[8]}'" if r[8] else "NULL"
                
                sql_insert = (
                    f"INSERT INTO pagos (fecha_recepcion, hora_recepcion, emisor, monto, referencia, mensaje_completo, estado, fecha_canje) "
                    f"VALUES ('{r[1]}', '{r[2]}', '{r[3]}', '{r[4]}', '{r[5]}', '{mensaje}', '{r[7]}', {fecha_canje}) "
                    f"ON CONFLICT (referencia) DO NOTHING;\n"
                )
                f.write(sql_insert)

        print(f"✅ ¡Respaldo completado con éxito!")
        print(f"📂 Archivo generado: {nombre_archivo}")
        
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Error durante el respaldo: {e}")

if __name__ == "__main__":
    ejecutar_respaldo()