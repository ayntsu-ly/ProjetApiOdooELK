import json
import socket
from datetime import datetime
from collections import Counter

logstash_host = "localhost"
logstash_port = 5000
db = "europ-alu"

def send_to_logstash(data, batch_size=500):
    total_records = len(data)
    if total_records == 0:
        print("⚠️ Aucune donnée à envoyer")
        return True

    print(f"🚀 Envoi de {total_records} enregistrements à Logstash...")
    doc_counter = Counter()

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(60)
        sock.connect((logstash_host, logstash_port))

        for start in range(0, total_records, batch_size):
            end = min(start + batch_size, total_records)
            batch = data[start:end]

            for record in batch:
                doc_type = record.get("document_type", "unknown")
                doc_counter[doc_type] += 1
                json_line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
                sock.sendall(json_line.encode("utf-8"))

            print(f"   ✅ {end}/{total_records} envoyés")

        sock.close()
        print(f"🎉 Tous les {total_records} enregistrements envoyés avec succès !")
        print("\n📈 === APERÇU DES DOCUMENTS ENVOYÉS ===")
        total = 0
        for doc_type, count in doc_counter.items():
            print(f"   📋 {doc_type}: {count} enregistrements")
            total += count
        print(f"\n🎯 TOTAL ENVOYÉ: {total} enregistrements")
        return True
    except Exception as e:
        print(f"❌ Erreur lors de l'envoi à Logstash: {e}")
        return False

def save_backup(data, filename=None):
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"odoo_sales_backup_{timestamp}.json"
    
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        print(f"💾 Sauvegarde créée: {filename}")
        return True
    except Exception as e:
        print(f"❌ Erreur lors de la sauvegarde: {e}")
        return False