import json
import locale
from datetime import datetime
from collections import defaultdict, Counter
import hashlib

# --- Fonctions utilitaires pour le traitement des donnée
def extract_id_from_many2one(field_value):
    if isinstance(field_value, list) and len(field_value) == 2:
        return field_value[0]
    elif isinstance(field_value, int):
        return field_value
    return None

def extract_name_from_many2one(field_value):
    if isinstance(field_value, list) and len(field_value) == 2:
        return field_value[1]
    return None

def get_target_model_for_field(model_name, field_name):
    field_model_mapping = {
        "partner_id": "res.partner",
        "user_id": "res.users",
        "team_id": "crm.team",
        "company_id": "res.company",
        "country_id": "res.country",
    }
    return field_model_mapping.get(field_name)

def resolve_relations(model_name, record, all_data, models_config, prefix="", depth=0):
    resolved_data = {}
    if depth > 2:
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
                if target_model and target_model in all_data and related_id in all_data[target_model]:
                    related_record = all_data[target_model][related_id]
                    relation_prefix = f"{prefix}{relation_field.replace('_id', '')}_"
                    
                    # Assigner seulement l'ID numérique, jamais le tableau
                    resolved_data[f"{relation_prefix}id"] = related_id
                    resolved_data[f"{relation_prefix}name"] = related_name or related_record.get('name', 'Nom inconnu')
                    
                    # Inclure l'objectif de l'équipe
                    if target_model == "crm.team":
                        resolved_data['team_invoiced_target'] = related_record.get('invoiced_target', 0)
                    
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
                    # Même si pas de données relatives, on assigne l'ID
                    resolved_data[f"{prefix}{relation_field.replace('_id', '')}_id"] = related_id
                    if related_name:
                        resolved_data[f"{prefix}{relation_field.replace('_id', '')}_name"] = related_name
    return resolved_data

def clean_record_fields(record):
    """Nettoie les champs du record pour s'assurer qu'ils sont compatibles avec Elasticsearch"""
    cleaned_record = {}
    
    for key, value in record.items():
        # Nettoyer les champs Many2One dans le record original
        if key.endswith('_id') and isinstance(value, list) and len(value) == 2:
            # Extraire seulement l'ID numérique
            cleaned_record[key] = value[0]
            # Créer un champ séparé pour le nom 
            name_key = key.replace('_id', '_name')
            if name_key not in record:  
                cleaned_record[name_key] = value[1]
        else:
            cleaned_record[key] = value
    
    return cleaned_record

# --- DEBUG: Fonction de vérification des doublons ---
def debug_sales_duplicates(universal_docs):
    """Vérifier les doublons dans les documents de vente"""
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
            print(f"    ID {sale_id}: {count} occurrences")
            dup_docs = [d for d in sales_docs if d.get('source_id') == sale_id]
            for i, doc in enumerate(dup_docs):
                print(f"      {i+1}. Montant: {doc.get('amount_total')}, Team: {doc.get('team_name')}")
        return True
    else:
        print("✅ Aucun doublon détecté dans les documents de vente")
        return False

def debug_amount_calculations(universal_docs):
    """Vérifier la cohérence des calculs de montants"""
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
    print("\n=== Création des documents universels ===")
    universal_documents = []
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
                # ✅ FIX: Nettoyer les champs du record avant traitement
                cleaned_record = clean_record_fields(record)
                
                universal_doc = {
                    "@timestamp": datetime.now().isoformat(),
                    "document_type": f"{model_name.replace('.', '_')}_analysis",
                    "source_model": model_name,
                    "source_id": record_id,
                    "odoo_database": "europ-alu",
                    "source": "odoo-flexible-connector",
                    **cleaned_record 
                }
                
                resolved_data = resolve_relations(model_name, cleaned_record, all_data, models_config)
                universal_doc.update(resolved_data)
                
                if model_name == 'sale.order':

                    state_labels = {
                        'draft': 'Brouillon',
                        'sent': 'Envoyé',
                        'sale': 'Bon de commande',
                        'done': 'Validé',
                        'cancel': 'Annulé',
                        'new' : 'Nouveau'
                    }
                    
                    current_state = cleaned_record.get('state')
                    
                    if current_state:
                        # Utiliser get() avec une valeur par défaut pour gérer les états inconnus
                        universal_doc['state_label'] = state_labels.get(current_state, current_state.capitalize())

                    date_order_str = cleaned_record.get('date_order')
                    universal_doc['year'] = 'Année inconnue'
                    universal_doc['month_name'] = 'Mois inconnu'
                    universal_doc['quarter'] = 'Trimestre inconnu'
                    universal_doc['day_of_year'] = 'Jour inconnu'

                    if date_order_str:
                        dt = None
                        date_formats = [
                            "%Y-%m-%dT%H:%M:%S.%f",
                            "%Y-%m-%dT%H:%M:%S",
                            "%d/%m/%Y %H:%M:%S",
                            "%d/%m/%Y",
                            "%Y-%m-%d %H:%M:%S",
                            "%Y-%m-%d"
                        ]
                        cleaned_date_str = str(date_order_str).replace('\u202f', ' ').replace('T', ' ').strip()
                        for fmt in date_formats:
                            try:
                                dt = datetime.strptime(cleaned_date_str, fmt)
                                break
                            except (ValueError, TypeError):
                                continue
                        
                        if dt is None:
                            print(f"⚠️ Erreur de format de date pour la commande {record_id} : '{cleaned_date_str}'. Aucun format ne correspond.")
                        
                        if dt:
                            universal_doc['date_order'] = dt.strftime("%Y-%m-%dT%H:%M:%SZ") # Format ISO pour Kibana
                            universal_doc['year'] = dt.year
                            universal_doc['month'] = dt.month
                            
                            month_names = {
                                1: 'janvier', 2: 'fevrier', 3: 'mars', 4: 'avril',
                                5: 'mai', 6: 'juin', 7: 'juillet', 8: 'aout', 
                                9: 'septembre', 10: 'octobre', 11: 'novembre', 12: 'decembre'
                            }
                            universal_doc['month_name'] = month_names.get(dt.month, 'mois_inconnu')
                            universal_doc['quarter'] = (dt.month - 1) // 3 + 1
                            universal_doc['day_of_year'] = dt.timetuple().tm_yday
                
                # VALIDATION FINALE: Vérifier que tous les champs *_id sont numériques
                for key, value in list(universal_doc.items()):
                    if key.endswith('_id') and not isinstance(value, (int, type(None))):
                        print(f"⚠️ ERREUR: Le champ {key} contient une valeur non-numérique: {value}")
                        if isinstance(value, list) and len(value) >= 1:
                            universal_doc[key] = value[0]
                            print(f"✅ Correction appliquée: {key} = {value[0]}")
                
                universal_documents.append(universal_doc)
            except Exception as e:
                print(f"❌ Erreur lors du traitement de {model_name} ID {record_id}: {e}")
    
    model_counts = Counter(doc['source_model'] for doc in universal_documents)
    for model, count in model_counts.items():
        print(f"✅ {model}: {count} documents créés")
    
    print(f"\n📊 TOTAL : {len(universal_documents)} documents universels créés")
    
    debug_sales_duplicates(universal_documents)
    debug_amount_calculations(universal_documents)
    
    return universal_documents

def create_aggregated_metrics(universal_docs):
    print("\n=== Calcul des métriques agrégées ===")
    print(" Note : Les objectifs sont déjà intégrés dans les documents de vente.")
    metrics_docs = []
    
    user_metrics = defaultdict(lambda: {'sales_total': 0, 'orders_count': set(), 'customers_count': set()})
    sales_team_metrics = defaultdict(lambda: {'sales_total': 0, 'orders_count': set(), 'customers_count': set()})
    state_metrics = defaultdict(lambda: {'orders_count': 0, 'sales_total': 0})
    team_state_metrics = defaultdict(lambda: {'orders_count': 0, 'sales_total': 0})
    team_month_metrics = defaultdict(lambda: {'orders_count': 0, 'sales_total': 0})
    
    # 1. Traitement des commandes de vente
    for doc in [d for d in universal_docs if d['source_model'] == 'sale.order']:
        amount_total = doc.get('amount_total', 0)
        order_id = doc.get('source_id')
        partner_name = doc.get('partner_name', 'Inconnu')
        user_name = doc.get('user_name', 'Inconnu')
        team_name = doc.get('team_name', 'Non assignée')
        state = doc.get('state', 'unknown')
        
        user_metrics[user_name]['sales_total'] += amount_total
        user_metrics[user_name]['orders_count'].add(order_id)
        user_metrics[user_name]['customers_count'].add(partner_name)
        
        sales_team_metrics[team_name]['sales_total'] += amount_total
        sales_team_metrics[team_name]['orders_count'].add(order_id)
        sales_team_metrics[team_name]['customers_count'].add(partner_name)

        state_metrics[state]['orders_count'] += 1
        state_metrics[state]['sales_total'] += amount_total

        team_state_metrics[(team_name, state)]['orders_count'] += 1
        team_state_metrics[(team_name, state)]['sales_total'] += amount_total

        if 'year' in doc and 'month_name' in doc and doc['year'] != 'Année inconnue':
            key = (doc['year'], doc['month_name'], team_name)
            team_month_metrics[key]['orders_count'] += 1
            team_month_metrics[key]['sales_total'] += amount_total
            
    # 2. Création des documents finaux (sans documents d'objectifs séparés)

    # Documents pour les métriques UTILISATEURS
    for user_name, metrics in user_metrics.items():
        orders_count = len(metrics['orders_count'])
        avg_order_value = metrics['sales_total'] / orders_count if orders_count else 0
        user_safe = user_name.replace(' ', '_').replace('/', '_').replace("'", "").lower()
        
        metrics_doc = {
            "@timestamp": datetime.now().isoformat(), 
            "document_type": "user_individual_metrics",
            "metric_type": "individual_sales_performance", 
            "odoo_database": "europ-alu",
            "source": "odoo-flexible-connector",
            "document_id": f"user_metrics_{user_safe}",
            "user_name": user_name,
            "sales_total": metrics['sales_total'], 
            "orders_count": orders_count,
            "customers_count": len(metrics['customers_count']), 
            "avg_order_value": avg_order_value
        }
        metrics_docs.append(metrics_doc)
        
    # Documents pour les métriques ÉQUIPES (agrégation)
    for team_name, metrics in sales_team_metrics.items():
        orders_count = len(metrics['orders_count'])
        avg_order_value = metrics['sales_total'] / orders_count if orders_count else 0
        team_safe = team_name.replace(' ', '_').replace('/', '_').replace("'", "").lower()
        
        metrics_doc = {
            "@timestamp": datetime.now().isoformat(), 
            "document_type": "team_aggregated_metrics",
            "metric_type": "team_sales_performance", 
            "odoo_database": "europ-alu",
            "source": "odoo-flexible-connector",
            "document_id": f"team_metrics_{team_safe}",
            "team_name": team_name,  
            "sales_total": metrics['sales_total'], 
            "orders_count": orders_count,
            "customers_count": len(metrics['customers_count']), 
            "avg_order_value": avg_order_value
        }
        metrics_docs.append(metrics_doc)

    # Documents pour les métriques par état
    for state, metrics in state_metrics.items():
        state_safe = state.replace(' ', '_').replace('/', '_').lower()
        
        metrics_doc = {
            "@timestamp": datetime.now().isoformat(), 
            "document_type": "order_state_metrics", 
            "metric_type": "sales_analysis_by_state", 
            "odoo_database": "europ-alu",
            "source": "odoo-flexible-connector",
            "document_id": f"state_metrics_{state_safe}",
            "state": state,
            "orders_count": metrics['orders_count'], 
            "sales_total": metrics['sales_total']
        }
        metrics_docs.append(metrics_doc)

    # Documents pour les métriques par équipe et état
    for (team_name, state), metrics in team_state_metrics.items():
        team_safe = team_name.replace(' ', '_').replace('/', '_').replace("'", "").lower()
        state_safe = state.replace(' ', '_').replace('/', '_').lower()
        
        metrics_doc = {
            "@timestamp": datetime.now().isoformat(), 
            "document_type": "team_state_metrics", 
            "metric_type": "sales_analysis_by_team_and_state", 
            "odoo_database": "europ-alu",
            "source": "odoo-flexible-connector",
            "document_id": f"team_state_{team_safe}_{state_safe}",
            "team_name": team_name,  
            "state": state,
            "orders_count": metrics['orders_count'], 
            "sales_total": metrics['sales_total']
        }
        metrics_docs.append(metrics_doc)

    print(f"✅ Documents de métriques agrégées créés: {len(metrics_docs)}")
    
    total_user_sales = sum(d['sales_total'] for d in [d for d in metrics_docs if d['document_type'] == 'user_individual_metrics'])
    total_team_sales = sum(d['sales_total'] for d in [d for d in metrics_docs if d['document_type'] == 'team_aggregated_metrics'])
    
    print(f"\n🔍 === VÉRIFICATION FINALE DES TOTAUX ===")
    print(f"💰 Total utilisateurs individuels: {total_user_sales:,.2f}€")
    print(f"💰 Total équipes agrégées: {total_team_sales:,.2f}€")
    print(f"✅ Les totaux {'correspondent' if abs(total_user_sales - total_team_sales) < 1 else 'NE correspondent PAS'}")
    
    return metrics_docs