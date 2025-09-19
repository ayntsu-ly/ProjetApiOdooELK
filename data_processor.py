import json
import locale
from datetime import datetime
from collections import defaultdict, Counter
import hashlib

# --- Fonctions utilitaires pour le traitement des données ---

def extract_id_from_many2one(field_value):
    """
    Extrait l'ID numérique d'un champ Many2one d'Odoo.
    Ces champs sont souvent des listes de la forme [ID, 'Nom'].
    S'il s'agit déjà d'un entier, il le retourne tel quel.
    """
    if isinstance(field_value, list) and len(field_value) == 2:
        return field_value[0]
    elif isinstance(field_value, int):
        return field_value
    return None

def extract_name_from_many2one(field_value):
    """
    Extrait le nom d'un champ Many2one d'Odoo.
    Retourne None si le format n'est pas une liste [ID, 'Nom'].
    """
    if isinstance(field_value, list) and len(field_value) == 2:
        return field_value[1]
    return None

def get_target_model_for_field(model_name, field_name):
    """
    Résolution des relations.
    """
    field_model_mapping = {
        "partner_id": "res.partner",
        "user_id": "res.users",
        "team_id": "crm.team",
        "company_id": "res.company",
        "country_id": "res.country",
    }
    return field_model_mapping.get(field_name)

def resolve_relations(model_name, record, all_data, models_config, prefix="", depth=0):
    """
    Parcourt un enregistrement Odoo et "résout" ses relations Many2one.
    Cela consiste à aller chercher les données des champs liés (ex: le nom du client)
    pour les aplatir dans le document principal. C'est essentiel pour le reporting dans Kibana.
    La fonction est récursive pour gérer les relations imbriquées (ex: utilisateur > équipe > manager).
    """
    resolved_data = {}
    if depth > 2:  # Limite la profondeur de la récursion pour éviter les boucles infinies
        return resolved_data
    
    config = models_config.get(model_name, {})
    relations = config.get("relations", [])
    
    for relation_field in relations:
        field_value = record.get(relation_field)
        if field_value and isinstance(field_value, (list, int)):
            related_id = extract_id_from_many2one(field_value)
            related_name = extract_name_from_many2one(field_value)
            
            if related_id:
                target_model = get_target_model_for_field(model_name, relation_field)
                
                # Vérifier si la relation cible existe avant de continuer
                if target_model and target_model in all_data and related_id in all_data[target_model]:
                    related_record = all_data[target_model][related_id]
                    relation_prefix = f"{prefix}{relation_field.replace('_id', '')}_"
                    
                    # On assigne les champs résolus avec un préfixe
                    resolved_data[f"{relation_prefix}id"] = related_id
                    resolved_data[f"{relation_prefix}name"] = related_name or related_record.get('name', 'Nom inconnu')
                    
                    # Logique spécifique pour ajouter l'objectif de l'équipe
                    if target_model == "crm.team":
                        resolved_data['team_invoiced_target'] = related_record.get('invoiced_target', 0)
                    
                    # Appel récursif pour résoudre les relations imbriquées
                    nested_resolved = resolve_relations(
                        target_model,
                        related_record,
                        all_data,
                        models_config,
                        relation_prefix,
                        depth + 1
                    )
                    resolved_data.update(nested_resolved)
                else:
                    # Gérer les cas où les données liées sont manquantes (par exemple, client supprimé)
                    resolved_data[f"{prefix}{relation_field.replace('_id', '')}_id"] = related_id
                    if related_name:
                        resolved_data[f"{prefix}{relation_field.replace('_id', '')}_name"] = related_name
    return resolved_data

def clean_record_fields(record):
    """
    Nettoie les champs du record pour s'assurer qu'ils sont compatibles avec Elasticsearch.
    La fonction convertit les listes Many2One en ID et nom séparés pour un meilleur mapping.
    """
    cleaned_record = {}
    
    for key, value in record.items():
        # Détecter et nettoyer les champs Many2One
        if key.endswith('_id') and isinstance(value, list) and len(value) == 2:
            # Extraire seulement l'ID numérique
            cleaned_record[key] = value[0]
            # Créer un champ séparé pour le nom
            name_key = key.replace('_id', '_name')
            if name_key not in record:  # Éviter d'écraser un champ existant
                cleaned_record[name_key] = value[1]
        else:
            cleaned_record[key] = value
    
    return cleaned_record

# --- Fonctions de débogage ---

def debug_sales_duplicates(universal_docs):
    """
    Vérifie la présence de doublons dans les documents de vente en se basant sur leur ID source.
    Cette fonction aide à identifier les problèmes dans le pipeline de données.
    """
    print("\n🔍 === DEBUG DES DOUBLONS DE VENTE ===")
    
    sales_docs = [d for d in universal_docs if d.get('source_model') == 'sale.order']
    print(f"📊 Total documents de vente: {len(sales_docs)}")
    
    source_ids = [d.get('source_id') for d in sales_docs]
    unique_ids = set(source_ids)
    print(f"🔢 IDs uniques: {len(unique_ids)}")
    
    if len(source_ids) != len(unique_ids):
        print("❌ PROBLÈME DÉTECTÉ: Doublons dans les documents de vente!")
        id_counts = Counter(source_ids)
        duplicates = {id_: count for id_, count in id_counts.items() if count > 1}
        print(f"⚠️ {len(duplicates)} IDs dupliqués:")
        for sale_id, count in list(duplicates.items())[:3]:
            print(f"    ID {sale_id}: {count} occurrences")
            dup_docs = [d for d in sales_docs if d.get('source_id') == sale_id]
            for i, doc in enumerate(dup_docs):
                print(f"      {i+1}. Montant: {doc.get('amount_total')}, Team: {doc.get('team_name')}")
        return True
    else:
        print("✅ Aucun doublon détecté dans les documents de vente")
        return False

def debug_amount_calculations(universal_docs):
    """
    Vérifie la cohérence des montants totaux.
    Elle compare la somme de tous les documents (qui peuvent inclure des doublons si la fonction deduplicate n'a pas été appelée)
    avec la somme des montants uniques par ID, ce qui aide à détecter les incohérences.
    """
    print("\n💰 === DEBUG DES CALCULS DE MONTANTS ===")
    
    sales_docs = [d for d in universal_docs if d.get('source_model') == 'sale.order']
    amounts = []
    unique_amounts = {}
    
    for doc in sales_docs:
        amount = doc.get('amount_total', 0)
        sale_id = doc.get('source_id')
        amounts.append(amount)
        if sale_id not in unique_amounts:
            unique_amounts[sale_id] = amount
        elif unique_amounts[sale_id] != amount:
            print(f"⚠️ Montants différents pour ID {sale_id}: {unique_amounts[sale_id]} vs {amount}")
    
    total_simple = sum(amounts)
    total_unique = sum(unique_amounts.values())
    print(f"📊 Total simple (tous documents): {total_simple:,.2f}€")
    print(f"📊 Total unique (par ID): {total_unique:,.2f}€")
    print(f"📊 Différence: {total_simple - total_unique:,.2f}€")
    
    if total_simple != total_unique:
        print("❌ INCOHÉRENCE: Les totaux ne correspondent pas!")
        ratio = total_simple / total_unique if total_unique > 0 else 0
        print(f"📈 Facteur de multiplication: {ratio:.2f}")
    else:
        print("✅ Totaux cohérents")
    
    return total_simple, total_unique


# --- Fonctions de traitement principales ---

def create_universal_documents(all_data, models_config):
    """
    Fonction principale qui transforme les données Odoo brutes en un format "universel"
    prêt à être indexé dans Elasticsearch.
    Elle gère l'enrichissement des données, la résolution des relations, le nettoyage des champs
    et l'ajout de champs de reporting (dates, états, etc.).
    """
    print("\n=== Création des documents universels ===")
    universal_documents = []
    
    # Tente de définir la locale pour les noms de mois
    try:
        locale.setlocale(locale.LC_TIME, 'fr_FR.utf8')
    except locale.Error:
        try:
            locale.setlocale(locale.LC_TIME, 'fra_fra')
        except locale.Error:
            print("⚠️ Impossible de définir la locale française. Les noms de mois pourraient être en anglais.")
    
    for model_name, records_dict in all_data.items():
        if not records_dict:
            print(f"⚠️ Aucune donnée pour {model_name}, on passe...")
            continue
        
        print(f"🔄 Traitement de {model_name}...")
        
        for record_id, record in records_dict.items():
            try:
                # Étape 1: Nettoyer les champs du record avant tout traitement
                cleaned_record = clean_record_fields(record)
                
                # Étape 2: Créer le document universel de base
                universal_doc = {
                    "@timestamp": datetime.now().isoformat(),
                    "document_type": f"{model_name.replace('.', '_')}_analysis",
                    "source_model": model_name,
                    "source_id": record_id,
                    "odoo_database": "europ-alu",
                    "source": "odoo-flexible-connector",
                    **cleaned_record
                }
                
                # Étape 3: Résoudre les relations pour enrichir le document
                resolved_data = resolve_relations(model_name, cleaned_record, all_data, models_config)
                universal_doc.update(resolved_data)
                
                # Étape 4: Ajouts spécifiques pour le modèle 'sale.order'
                if model_name == 'sale.order':
                    
                    if 'amount_total' in universal_doc:
                        try:
                            amount = universal_doc['amount_total']
                            if isinstance(amount, (int, float)):
                                universal_doc['amount_total'] = round(float(amount), 2)
                        except (ValueError, TypeError):
                            pass     
                    # Ajouter un champ 'state_label' convivial pour le reporting
                    state_labels = {
                        'draft': 'Brouillon', 'sent': 'Envoyé', 'sale': 'Bon de commande',
                        'done': 'Validé', 'cancel': 'Annulé', 'new' : 'Nouveau'
                    }
                    current_state = cleaned_record.get('state')
                    if current_state:
                        universal_doc['state_label'] = state_labels.get(current_state, current_state.capitalize())

                    # Initialiser les dates pour éviter les erreurs
                    universal_doc['create_date'] = None
                    universal_doc['date_order'] = None
                    
                    # Création de la fonction de traitement des dates pour éviter la duplication de code
                    def process_date(date_str, field_prefix):
                        if not date_str:
                            return None
                        
                        dt = None
                        date_formats = [
                            "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S",
                            "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"
                        ]
                        cleaned_date_str = str(date_str).replace('\u202f', ' ').replace('T', ' ').strip()
                        for fmt in date_formats:
                            try:
                                dt = datetime.strptime(cleaned_date_str, fmt)
                                break
                            except (ValueError, TypeError):
                                continue
                        
                        if dt:
                            doc_data = {
                                f'{field_prefix}': dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                f'{field_prefix}_year': dt.year,
                                f'{field_prefix}_month': dt.month,
                                f'{field_prefix}_quarter': (dt.month - 1) // 3 + 1,
                                f'{field_prefix}_day_of_year': dt.timetuple().tm_yday
                            }
                            month_names = {
                                1: 'janvier', 2: 'fevrier', 3: 'mars', 4: 'avril', 5: 'mai',
                                6: 'juin', 7: 'juillet', 8: 'aout', 9: 'septembre',
                                10: 'octobre', 11: 'novembre', 12: 'decembre'
                            }
                            doc_data[f'{field_prefix}_month_name'] = month_names.get(dt.month, 'mois_inconnu')
                            return doc_data
                        else:
                            print(f"⚠️ Erreur de format de date pour le champ '{field_prefix}' pour la commande {record_id} : '{cleaned_date_str}'. Aucun format ne correspond.")
                            return None

                    # Traiter la date de création
                    create_date_str = cleaned_record.get('create_date')
                    if create_date_str:
                        create_date_doc = process_date(create_date_str, 'create_date')
                        if create_date_doc:
                            universal_doc.update(create_date_doc)    

                    date_order_str = cleaned_record.get('date_order')
                    if date_order_str:
                        date_order_doc = process_date(date_order_str, 'date_order')
                        if date_order_doc:
                            universal_doc.update(date_order_doc)
                            
                # Étape 5: Validation finale
                for key, value in list(universal_doc.items()):
                    if key.endswith('_id') and not isinstance(value, (int, type(None))):
                        print(f"⚠️ ERREUR: Le champ {key} contient une valeur non-numérique: {value}")
                        if isinstance(value, list) and len(value) >= 1:
                            universal_doc[key] = value[0]
                            print(f"✅ Correction appliquée: {key} = {value[0]}")
                
                # Ajouter le document enrichi à la liste
                universal_documents.append(universal_doc)
            except Exception as e:
                print(f"❌ Erreur lors du traitement de {model_name} ID {record_id}: {e}")
    
    # Statistiques de fin de fonction
    model_counts = Counter(doc['source_model'] for doc in universal_documents)
    for model, count in model_counts.items():
        print(f"✅ {model}: {count} documents créés")
    
    print(f"\n📊 TOTAL : {len(universal_documents)} documents universels créés")
    
    # Exécuter les fonctions de débogage
    debug_sales_duplicates(universal_documents)
    debug_amount_calculations(universal_documents)
    
    return universal_documents
