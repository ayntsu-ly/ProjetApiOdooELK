import requests
import json
import socket
import sys
from datetime import datetime
import time

url = "https://lab-odoo.europ-alu.com/jsonrpc"
db = "europ-alu"
username = "direction@vertec.mg"
password = "1234"

def authenticate():
    """Authentification avec Odoo"""
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": "common",
            "method": "login",
            "args": [db, username, password]
        },
        "id": 1,
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10).json()
        uid = response.get("result")
        
        if not uid:
            print("Erreur d'authentification:", response.get("error"))
            return None
            
        print("UID:", uid)
        return uid
    except Exception as e:
        print(f"Erreur lors de l'authentification: {e}")
        return None

def fetch_data(uid):
    """Récupération des données depuis Odoo"""
    models_to_fetch = {
        "purchase.order": {
            "domain": [[]],
            "fields": ["id", "name", "partner_id", "state", "date_order", "amount_total"],
            "limit": 10  
        },
        "sale.order": {
            "domain": [[]],
            "fields": ["id", "name", "partner_id", "amount_total", "state", "date_order"],
            "limit": 20
        },
        "res.partner": {
            "domain": [[]],
            "fields": ["id", "name", "email", "phone", "is_company", "customer_rank"],
            "limit": 50
        },
        "stock.quant": {
            "domain": [[]],
            "fields": ["id", "product_id", "inventory_quantity", "location_id", "lot_id"],
            "limit": 10
        },
        "product.template": {
            "domain": [[]],
            "fields" : ["name","list_price","default_code","qty_available","virtual_available","outgoing_qty","taxes_id","categ_id","sage_ref"],
            "limit" : 50
        },
        "stock.move": {
            "domain" : [[]],
            "fields": ["product_id","product_uom_qty"],
            "limit" : 60  
        },
    
        "product.product" : {
            "domain" : [[]],
            "fields" : ["name","sale_ok","service_tracking","categ_id","default_code","sage_color"],
            "limit" : 10 
        },
        "stock.picking" : {
            "domain" : [[]],
            "fields" : ["partner_id","picking_type_id","location_dest_id","scheduled_date","date_deadline","origin"],
            "limit" : 10
        }
    }

    results = {}

    for model, params in models_to_fetch.items():
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    db,
                    uid,
                    password,
                    model,
                    "search_read",
                    params["domain"],
                    {"fields": params["fields"], "limit": params["limit"]}
                ],
            },
            "id": model,
        }

        try:
            response = requests.post(url, json=payload, timeout=10).json()
            
            if "error" in response:
                print(f"Erreur pour le modèle {model}: {response['error']}")
                continue
                
            results[model] = response.get("result")
            print(f"✓ Données récupérées pour {model}: {len(results[model])} enregistrements")
            
        except Exception as e:
            print(f"Erreur lors de la récupération de {model}: {e}")
            continue

    return results

def format_data_for_logstash(data):
    """Formate les données pour Logstash avec métadonnées et transforme les Many2one"""
    formatted_records = []
    
    for model_name, records in data.items():
        if not records:
            continue
            
        for record in records:
            new_record = {}
            for k, v in record.items():
                # Si c'est un Many2one [id, name], transformer en chaîne ou dict
                if isinstance(v, list) and len(v) == 2 and isinstance(v[0],int):
                    new_record[k] = {"id" : v[0], "name" : v[1]}
                elif v is None:
                    new_record[k] = {"id": None , "name" : None}   
                else:
                    new_record[k] = v    


            log_record = {
                "@timestamp": datetime.utcnow().isoformat(),
                "odoo_model": model_name,
                "odoo_database": db,
                "data": new_record,
                "source": "odoo-python-connector"
            }
            formatted_records.append(log_record)
    
    return formatted_records


def send_to_logstash(data, batch_size=10):
    """Envoi des données à Logstash par lots"""
    logstash_host = "localhost"
    logstash_port = 5000
    
    # Formater les données
    formatted_data = format_data_for_logstash(data)
    total_records = len(formatted_data)
    
    if total_records == 0:
        print("Aucune donnée à envoyer")
        return True
    
    print(f"Envoi de {total_records} enregistrements à Logstash...")
    
    try:
        # Envoyer par lots
        for i in range(0, total_records, batch_size):
            batch = formatted_data[i:i+batch_size]
            
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10)
                s.connect((logstash_host, logstash_port))
                
                # Envoyer chaque enregistrement sur une ligne séparée (JSON Lines)
                for record in batch:
                    json_line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
                    s.sendall(json_line.encode('utf-8'))
            
            print(f"✓ Lot {i//batch_size + 1} envoyé ({len(batch)} enregistrements)")
            time.sleep(0.1)  # Petite pause entre les lots
            
        print(f"✓ Tous les {total_records} enregistrements ont été envoyés avec succès !")
        return True
        
    except ConnectionRefusedError:
        print("❌ Erreur: Impossible de se connecter à Logstash. Vérifiez que le service est démarré et que le port 5000 est ouvert.")
        return False
    except Exception as e:
        print(f"❌ Erreur lors de l'envoi à Logstash: {e}")
        return False

def save_backup(data, filename=None):
    """Sauvegarde locale des données en JSON"""
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"odoo_backup_{timestamp}.json"
    
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        print(f"✓ Sauvegarde créée: {filename}")
        return True
    except Exception as e:
        print(f"❌ Erreur lors de la sauvegarde: {e}")
        return False

def main():
    print("=== Début de la récupération des données Odoo ===")
    start_time = datetime.now()
    
    # 1. Authentification
    uid = authenticate()
    if not uid:
        print("❌ Échec de l'authentification. Arrêt du script.")
        sys.exit(1)
    
    # 2. Récupération des données
    print("\n=== Récupération des données ===")
    results = fetch_data(uid)
    
    if not results:
        print("❌ Aucune donnée récupérée. Arrêt du script.")
        sys.exit(1)
    
    # 3. Affichage des résultats
    print("\n=== Aperçu des données ===")
    total_records = 0
    for model, data in results.items():
        if data:
            count = len(data)
            total_records += count
            print(f"{model}: {count} enregistrements")
    
    print(f"Total: {total_records} enregistrements")
    
    # 4. Sauvegarde locale (optionnelle)
    print("\n=== Sauvegarde locale ===")
    save_backup(results)
    
    # 5. Envoi à Logstash
    print("\n=== Envoi à Logstash ===")
    success = send_to_logstash(results)
    
    # 6. Résumé
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    print(f"\n=== Résumé ===")
    print(f"Durée totale: {duration:.2f} secondes")
    print(f"Enregistrements traités: {total_records}")
    
    if success:
        print("✅ Script exécuté avec succès !")
    else:
        print("⚠️  Script terminé avec des erreurs.")
        sys.exit(1)

if __name__ == "__main__":
    main()