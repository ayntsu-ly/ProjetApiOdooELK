import os
from dotenv import load_dotenv
import json
import socket
import requests
import time
from datetime import datetime
from collections import Counter

# Charger les variables depuis le fichie
load_dotenv()

# Configuration du data loader
logstash_host = os.getenv("LOGSTASH_HOST")
logstash_port = int(os.getenv("LOGSTASH_PORT"))
elasticsearch_host = os.getenv("ELASTICSEARCH_HOST")
elasticsearch_port = int(os.getenv("ELASTICSEARCH_PORT"))
db = os.getenv("ODOO_DB")

def wait_for_elasticsearch_sync(index_name, timeout=90):
    """Attend que Elasticsearch synchronise après une opération"""
    print(f"⏳ Attente de la synchronisation pour l'index '{index_name}'...")
    time.sleep(2)

    try:
        response = requests.post(
            f"http://{elasticsearch_host}:{elasticsearch_port}/{index_name}/_refresh",
            timeout=10
        )
        if response.status_code == 200:
            print(f"✅ Index {index_name} rafraîchi")
    except Exception as e:
        print(f"⚠️ Impossible de rafraîchir l'index {index_name}: {e}")

def clean_old_data(index_names):
    """Supprime les anciennes données de manière plus fiable pour chaque index spécifié"""
    print("🧹 Nettoyage complet des anciennes données...")
    
    for index_name in index_names:
        delete_query = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"odoo_database": db}},
                        {"term": {"source": "odoo-flexible-connector"}}
                    ]
                }
            }
        }
        
        try:
            print(f"-> Nettoyage de l'index {index_name}...")
            response = requests.post(
                f"http://{elasticsearch_host}:{elasticsearch_port}/{index_name}/_delete_by_query?refresh=true",
                json=delete_query,
                headers={"Content-Type": "application/json"},
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                deleted = result.get('deleted', 0)
                print(f"✅ {deleted} documents supprimés de {index_name}")
            else:
                print(f"⚠️ Problème de suppression pour {index_name}: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur lors du nettoyage de l'index {index_name}: {e}")
            return False
            
    return True

def validate_and_fix_record(record):
    """Valide et corrige un enregistrement avant l'envoi"""
    fixed_record = {}
    issues_found = []
    
    for key, value in record.items():
        if key.endswith('_id') and value is not None:
            if isinstance(value, list) and len(value) >= 1:
                try:
                    fixed_record[key] = int(value[0])
                    if len(value) > 1 and value[1]:
                        name_key = key.replace('_id', '_name')
                        if name_key not in record:
                            fixed_record[name_key] = str(value[1])
                    issues_found.append(f"Champ {key}: converti")
                except (ValueError, TypeError):
                    fixed_record[key] = None
                    issues_found.append(f"Champ {key}: valeur invalide, mis à None")
            elif isinstance(value, (int, str)):
                try:
                    fixed_record[key] = int(value)
                except (ValueError, TypeError):
                    fixed_record[key] = None
                    issues_found.append(f"Champ {key}: impossible de convertir")
            else:
                fixed_record[key] = value
        else:
            fixed_record[key] = value
    
    if issues_found:
        doc_id = record.get('document_id', 'inconnu')
        print(f"🔧 Corrections appliquées au document {doc_id}: {issues_found}")
    
    return fixed_record

def generate_consistent_document_id(record):
    """Génère un ID de document consistant pour éviter les doublons"""
    import hashlib
    import json

    source_model = record.get('source_model', 'unknown_model').replace('.', '_')
    source_id = record.get('source_id', 'no_id')

    if source_model != 'unknown_model' and source_id != 'no_id':
        # F-string fermée correctement
        return f"{source_model}_{source_id}"
    else:
        content = {
            'doc_type': record.get('document_type', 'unknown'),
            'source_id': source_id,
            'database': record.get('odoo_database', '')
        }
        hash_suffix = hashlib.md5(json.dumps(content, sort_keys=True).encode()).hexdigest()[:8]
        return f"{source_model}_{source_id}_{hash_suffix}"


def send_to_logstash(data, models_config, clean_before_send=True):
    """Envoi optimisé à Logstash et attente de la synchronisation"""
    total_records = len(data)
    if total_records == 0:
        print("⚠️ Aucune donnée à envoyer")
        return True
    
    if clean_before_send:
        index_names_to_clean = list(models_config.keys())
        if not clean_old_data(index_names_to_clean):
            print("⚠️ Échec du nettoyage, continuons quand même...")

    print(f"🚀 Envoi de {total_records} enregistrements à Logstash...")
    processed_ids = set() 
    validation_errors = 0

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(60)
        sock.connect((logstash_host, logstash_port))

        for record in data:
            try:
                validated_record = validate_and_fix_record(record)
                document_id = generate_consistent_document_id(validated_record)
                
                if document_id in processed_ids:
                    continue
                
                processed_ids.add(document_id)
                validated_record['document_id'] = document_id
                validated_record['processing_timestamp'] = datetime.now().isoformat()
                
                json_line = json.dumps(validated_record, ensure_ascii=False, default=str) + "\n"
                sock.sendall(json_line.encode("utf-8"))
            except Exception as e:
                print(f"❌ Erreur envoi document: {e}")
                validation_errors += 1
                continue

        sock.close()
        
        successful_records = len(processed_ids)
        print(f"🎉 {successful_records} enregistrements uniques envoyés avec succès !")
        
        if validation_errors > 0:
            print(f"⚠️ {validation_errors} erreurs de validation/envoi")
        
        # Attente de la synchronisation pour chaque index
        for model_name in models_config.keys():
            wait_for_elasticsearch_sync(model_name)
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de l'envoi à Logstash: {e}")
        return False
