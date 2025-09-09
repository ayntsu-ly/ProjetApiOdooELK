import os
from dotenv import load_dotenv
import json
import socket
import requests
import time
from datetime import datetime
from collections import Counter

# Charger les variables depuis le fichier 
load_dotenv()

# Configuration du data loader
logstash_host = os.getenv("LOGSTASH_HOST")
logstash_port = int(os.getenv("LOGSTASH_PORT"))
elasticsearch_host = os.getenv("ELASTICSEARCH_HOST")
elasticsearch_port = int(os.getenv("ELASTICSEARCH_PORT")) 
db = os.getenv("ODOO_DB") 

def wait_for_elasticsearch_sync(index_name="odoo_data_v91", timeout=30):
    """Attend que Elasticsearch synchronise après suppression"""
    print("⏳ Attente de la synchronisation Elasticsearch...")
    time.sleep(2) 
    
    # Forcer un refresh de l'index
    try:
        response = requests.post(
            f"http://{elasticsearch_host}:{elasticsearch_port}/{index_name}/_refresh",
            timeout=10
        )
        if response.status_code == 200:
            print(f"✅ Index {index_name} rafraîchi")
    except:
        print(f"⚠️ Impossible de rafraîchir l'index {index_name}")

def clean_old_data(index_name="odoo_data_v91"):
    """Supprime les anciennes données de manière plus fiable"""
    print("🧹 Nettoyage complet des anciennes données...")
    
    # 1. Supprimer par base de données
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
        response = requests.post(
            f"http://{elasticsearch_host}:{elasticsearch_port}/{index_name}/_delete_by_query?refresh=true",
            json=delete_query,
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            deleted = result.get('deleted', 0)
            print(f"✅ {deleted} documents supprimés par requête")
            
            # Attendre la synchronisation
            wait_for_elasticsearch_sync(index_name)
            
            return True
        else:
            print(f"⚠️ Problème suppression: {response.status_code} - {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Impossible de se connecter à Elasticsearch: {e}")
        
        # Méthode alternative : supprimer tout l'index et le recréer
        print("🔄 Tentative de suppression/recréation de l'index...")
        try:
            # Supprimer l'index
            delete_response = requests.delete(
                f"http://{elasticsearch_host}:{elasticsearch_port}/{index_name}",
                timeout=30
            )
            if delete_response.status_code in [200, 404]:
                print("✅ Index supprimé")
                time.sleep(1)
                return True
        except Exception as delete_error:
            print(f"❌ Erreur suppression index: {delete_error}")
        
        return False

def validate_and_fix_record(record):
    """Valide et corrige un enregistrement avant l'envoi"""
    fixed_record = {}
    issues_found = []
    
    for key, value in record.items():
        # ✅ FIX CRITIQUE: Vérifier tous les champs _id
        if key.endswith('_id') and value is not None:
            if isinstance(value, list):
                if len(value) >= 1 and isinstance(value[0], (int, str)):
                    try:
                        fixed_record[key] = int(value[0])
                        issues_found.append(f"Champ {key}: converti de {value} vers {value[0]}")
                        
                        # Créer un champ nom si disponible
                        if len(value) > 1 and value[1]:
                            name_key = key.replace('_id', '_name')
                            if name_key not in record:
                                fixed_record[name_key] = str(value[1])
                    except (ValueError, TypeError):
                        fixed_record[key] = None
                        issues_found.append(f"Champ {key}: valeur invalide {value}, défini à None")
                else:
                    fixed_record[key] = None
                    issues_found.append(f"Champ {key}: tableau vide ou invalide, défini à None")
            elif isinstance(value, (int, str)):
                try:
                    fixed_record[key] = int(value)
                except (ValueError, TypeError):
                    fixed_record[key] = None
                    issues_found.append(f"Champ {key}: impossible de convertir '{value}' en entier")
            else:
                fixed_record[key] = value
        else:
            fixed_record[key] = value
    
    if issues_found:
        doc_id = record.get('document_id', 'inconnu')
        print(f"🔧 Corrections appliquées au document {doc_id}:")
        for issue in issues_found[:3]: 
            print(f"   - {issue}")
        if len(issues_found) > 3:
            print(f"   - ... et {len(issues_found) - 3} autres corrections")
    
    return fixed_record

def generate_consistent_document_id(record):
    """Génère un ID de document consistant pour éviter les doublons"""
    import hashlib
    import json
    
    # Extraire l'ID source de manière sécurisée
    source_id = record.get('source_id')
    if isinstance(source_id, list) and len(source_id) > 0:
        source_id = source_id[0]
    source_id = str(source_id) if source_id is not None else 'no_id'
    
    # Cas spécifiques pour les documents universels seulement
    if record.get('source_model') == 'sale.order':
        return f"sale_order_{source_id}"
    elif record.get('source_model') in ['res.partner', 'res.users', 'res.company', 'res.country', 'crm.team']:
        source_model = record.get('source_model').replace('.', '_')
        return f"{source_model}_{source_id}"
    else:
        # Fallback générique avec un hachage pour tout autre type de document
        doc_type = record.get('document_type', 'unknown')
        doc_type_safe = str(doc_type).replace(' ', '_').lower()
        content = {
            'doc_type': doc_type,
            'source_id': source_id,
            'database': record.get('odoo_database', '')
        }
        hash_suffix = hashlib.md5(json.dumps(content, sort_keys=True).encode()).hexdigest()[:8]
        return f"{doc_type_safe}_{source_id}_{hash_suffix}"

def send_to_logstash(data, batch_size=500, clean_before_send=True):
    """Envoi optimisé avec gestion des doublons et validation des données"""
    total_records = len(data)
    if total_records == 0:
        print("⚠️ Aucune donnée à envoyer")
        return True

    # Nettoyage des anciennes données
    if clean_before_send:
        if not clean_old_data():
            print("⚠️ Échec du nettoyage, continuons quand même...")

    print(f"🚀 Envoi de {total_records} enregistrements à Logstash...")
    doc_counter = Counter()
    processed_ids = set()  # Pour détecter les doublons locaux
    validation_errors = 0

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(60)
        sock.connect((logstash_host, logstash_port))

        for start in range(0, total_records, batch_size):
            end = min(start + batch_size, total_records)
            batch = data[start:end]

            for record in batch:
                # ✅ ÉTAPE 1: Validation et correction du record
                try:
                    validated_record = validate_and_fix_record(record)
                except Exception as e:
                    print(f"❌ Erreur validation record: {e}")
                    validation_errors += 1
                    continue
                
                # ✅ ÉTAPE 2: Générer un ID de document consistant
                try:
                    document_id = generate_consistent_document_id(validated_record)
                except Exception as e:
                    print(f"❌ Erreur génération ID: {e}")
                    validation_errors += 1
                    continue
                
                # ✅ ÉTAPE 3: Vérifier les doublons locaux
                if document_id in processed_ids:
                    print(f"⚠️ Doublon détecté et ignoré: {document_id}")
                    continue
                
                processed_ids.add(document_id)
                validated_record['document_id'] = document_id
                
                # ✅ ÉTAPE 4: Ajouter un timestamp de traitement
                validated_record['processing_timestamp'] = datetime.now().isoformat()
                
                # ✅ ÉTAPE 5: Debug pour champ user_id (pour vérifier la correction)
                if 'user_id' in validated_record:
                    user_id_val = validated_record['user_id']
                    if not isinstance(user_id_val, (int, type(None))):
                        print(f"⚠️ ALERTE: user_id encore non-numérique dans {document_id}: {user_id_val}")

                doc_type = validated_record.get("document_type", "unknown")
                doc_counter[doc_type] += 1
                
                # ✅ ÉTAPE 6: Envoi sécurisé
                try:
                    json_line = json.dumps(validated_record, ensure_ascii=False, default=str) + "\n"
                    sock.sendall(json_line.encode("utf-8"))
                except Exception as e:
                    print(f"❌ Erreur envoi document {document_id}: {e}")
                    validation_errors += 1
                    continue

            print(f"   ✅ {end}/{total_records} traités")

        sock.close()
        
        successful_records = len(processed_ids)
        print(f"🎉 {successful_records} enregistrements uniques envoyés avec succès !")
        
        if validation_errors > 0:
            print(f"⚠️ {validation_errors} erreurs de validation/envoi détectées")
        
        # Statistiques détaillées
        print("\n📈 === APERÇU DES DOCUMENTS ENVOYÉS ===")
        total = 0
        for doc_type, count in doc_counter.items():
            print(f"   📋 {doc_type}: {count} enregistrements")
            total += count
        print(f"\n🎯 TOTAL UNIQUE ENVOYÉ: {total} enregistrements")
        
        if successful_records != total_records:
            skipped = total_records - successful_records
            print(f"🔍 Enregistrements ignorés (doublons/erreurs): {skipped}")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de l'envoi à Logstash: {e}")
        return False

def save_backup(data, filename=None):
    """Sauvegarde avec horodatage et validation"""
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"odoo_sales_backup_{timestamp}.json"
    
    # ✅ Valider les données avant sauvegarde
    validated_data = []
    for record in data:
        try:
            validated_record = validate_and_fix_record(record)
            validated_data.append(validated_record)
        except Exception as e:
            print(f"⚠️ Erreur validation record pour backup: {e}")
            validated_data.append(record)  # Garder l'original en cas d'erreur
    
    # Ajouter des métadonnées à la sauvegarde
    backup_data = {
        "metadata": {
            "backup_timestamp": datetime.now().isoformat(),
            "total_records": len(validated_data),
            "original_records": len(data),
            "odoo_database": db,
            "validation_applied": True
        },
        "data": validated_data
    }
    
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False, default=str)
        print(f"💾 Sauvegarde créée: {filename}")
        return True
    except Exception as e:
        print(f"❌ Erreur lors de la sauvegarde: {e}")
        return False