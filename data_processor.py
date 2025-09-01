import json
import locale
from datetime import datetime
from collections import defaultdict, Counter

# --- Fonctions utilitaires pour le traitement des données ---
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
            
            if related_id:
                target_model = get_target_model_for_field(model_name, relation_field)
                if target_model and target_model in all_data and related_id in all_data[target_model]:
                    related_record = all_data[target_model][related_id]
                    relation_prefix = f"{prefix}{relation_field.replace('_id', '')}_"
                    
                    resolved_data[f"{relation_prefix}id"] = related_id
                    resolved_data[f"{relation_prefix}name"] = extract_name_from_many2one(field_value)
                    
                    nested_resolved = resolve_relations(
                        target_model, 
                        related_record, 
                        all_data, 
                        models_config, 
                        relation_prefix, 
                        depth + 1
                    )
                    resolved_data.update(nested_resolved)
    return resolved_data

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
                universal_doc = {
                    "@timestamp": datetime.now().isoformat(),
                    "document_type": f"{model_name.replace('.', '_')}_analysis",
                    "source_model": model_name,
                    "source_id": record_id,
                    "odoo_database": "europ-alu",
                    "source": "odoo-flexible-connector",
                    **record
                }
                
                resolved_data = resolve_relations(model_name, record, all_data, models_config)
                universal_doc.update(resolved_data)
                
                # --- DÉBUT DE LA NOUVELLE MODIFICATION ---
                if model_name == 'sale.order':
                    date_order_str = record.get('date_order')
                    
                    universal_doc['year'] = 'Année inconnue'
                    universal_doc['month_name'] = 'Mois inconnu'
                    universal_doc['quarter'] = 'Trimestre inconnu'
                    universal_doc['day_of_year'] = 'Jour inconnu'

                    if date_order_str:
                        dt = None
                        try:
                            # Tente d'abord le format ISO 8601 (YYYY-MM-DD HH:MM:SS)
                            dt = datetime.fromisoformat(date_order_str)
                        except ValueError:
                            try:
                                # Si le format ISO échoue, tente le format européen (DD/MM/YYYY HH:MM:SS)
                                dt = datetime.strptime(date_order_str, "%d/%m/%Y %H:%M:%S")
                            except (ValueError, TypeError) as e:
                                # Si les deux formats échouent, le document conserve les valeurs 'inconnues'
                                print(f"⚠️ Erreur de format de date pour la commande {record_id} : {date_order_str}. Erreur: {e}")
                        
                        if dt:
                            universal_doc['year'] = dt.year
                            universal_doc['month'] = dt.month
                            universal_doc['month_name'] = dt.strftime("%B")
                            universal_doc['quarter'] = (dt.month - 1) // 3 + 1
                            universal_doc['day_of_year'] = dt.timetuple().tm_yday
                
                universal_documents.append(universal_doc)
            except Exception as e:
                print(f"❌ Erreur lors du traitement de {model_name} ID {record_id}: {e}")
    
    print(f"✅ {model_name}: {len([doc for doc in universal_documents if doc['source_model'] == model_name])} documents créés")
    print(f"\n📊 TOTAL : {len(universal_documents)} documents universels créés")
    return universal_documents

# La fonction `create_aggregated_metrics` reste inchangée
def create_aggregated_metrics(universal_docs):
    print("\n=== Calcul des métriques agrégées ===")
    metrics_docs = []
    partner_metrics = defaultdict(lambda: {'sales_total': 0, 'orders_count': set()})
    user_metrics = defaultdict(lambda: {'sales_total': 0, 'orders_count': set(), 'customers_count': set()})
    sales_team_metrics = defaultdict(lambda: {'sales_total': 0, 'orders_count': set(), 'customers_count': set()})
    team_region_metrics = defaultdict(lambda: {'sales_total': 0, 'orders_count': set()})
    state_metrics = defaultdict(lambda: {'orders_count': 0, 'sales_total': 0})
    team_state_metrics = defaultdict(lambda: {'orders_count': 0, 'sales_total': 0})
    team_month_metrics = defaultdict(lambda: {'orders_count': 0, 'sales_total': 0})
    
    for doc in [d for d in universal_docs if d['source_model'] == 'sale.order']:
        total_amount = doc.get('amount_total', 0)
        order_id = doc.get('id')
        
        partner_name = doc.get('partner_name', 'Inconnu')
        user_name = doc.get('user_name', 'Inconnu')
        team_name = doc.get('team_name', 'Non assignée')
        state = doc.get('state', 'unknown')
        
        partner_metrics[partner_name]['sales_total'] += total_amount
        partner_metrics[partner_name]['orders_count'].add(order_id)
        
        user_metrics[user_name]['sales_total'] += total_amount
        user_metrics[user_name]['orders_count'].add(order_id)
        user_metrics[user_name]['customers_count'].add(partner_name)
        
        sales_team_metrics[team_name]['sales_total'] += total_amount
        sales_team_metrics[team_name]['orders_count'].add(order_id)
        sales_team_metrics[team_name]['customers_count'].add(partner_name)

        state_metrics[state]['orders_count'] += 1
        state_metrics[state]['sales_total'] += total_amount

        team_state_metrics[(team_name, state)]['orders_count'] += 1
        team_state_metrics[(team_name, state)]['sales_total'] += total_amount

        if 'year' in doc and 'month_name' in doc:
            key = (doc['year'], doc['month_name'], team_name)
            team_month_metrics[key]['orders_count'] += 1
            team_month_metrics[key]['sales_total'] += total_amount

    for user_name, metrics in user_metrics.items():
        orders_count = len(metrics['orders_count'])
        avg_order_value = metrics['sales_total'] / orders_count if orders_count else 0
        metrics_doc = {
            "@timestamp": datetime.now().isoformat(), "document_type": "user_metrics", "metric_type": "sales_performance", "odoo_database": "europ-alu",
            "source": "odoo-flexible-connector", "user_name": user_name,
            "sales_total": metrics['sales_total'], "orders_count": orders_count,
            "customers_count": len(metrics['customers_count']), "avg_order_value": avg_order_value
        }
        metrics_docs.append(metrics_doc)
        
    for team_name, metrics in sales_team_metrics.items():
        orders_count = len(metrics['orders_count'])
        avg_order_value = metrics['sales_total'] / orders_count if orders_count else 0
        metrics_doc = {
            "@timestamp": datetime.now().isoformat(), "document_type": "sales_team_metrics", "metric_type": "sales_performance", "odoo_database": "europ-alu",
            "source": "odoo-flexible-connector", "sales_team_name": team_name,
            "sales_total": metrics['sales_total'], "orders_count": orders_count,
            "customers_count": len(metrics['customers_count']), "avg_order_value": avg_order_value
        }
        metrics_docs.append(metrics_doc)

    for state, metrics in state_metrics.items():
        metrics_doc = {
            "@timestamp": datetime.now().isoformat(), "document_type": "order_state_metrics", "metric_type": "sales_analysis_by_state", "odoo_database": "europ-alu",
            "source": "odoo-flexible-connector", "state": state,
            "orders_count": metrics['orders_count'], "sales_total": metrics['sales_total']
        }
        metrics_docs.append(metrics_doc)

    for (team_name, state), metrics in team_state_metrics.items():
        metrics_doc = {
            "@timestamp": datetime.now().isoformat(), "document_type": "team_state_metrics", "metric_type": "sales_analysis_by_team_and_state", "odoo_database": "europ-alu",
            "source": "odoo-flexible-connector", "sales_team_name": team_name, "state": state,
            "orders_count": metrics['orders_count'], "sales_total": metrics['sales_total']
        }
        metrics_docs.append(metrics_doc)
        
    for (year, month_name, team_name), metrics in team_month_metrics.items():
        metrics_doc = {
            "@timestamp": datetime.now().isoformat(), "document_type": "team_monthly_metrics", "metric_type": "sales_analysis_by_month_and_team", "odoo_database": "europ-alu",
            "source": "odoo-flexible-connector", "year": year, "month_name": month_name, "sales_team_name": team_name,
            "orders_count": metrics['orders_count'], "sales_total": metrics['sales_total']
        }
        metrics_docs.append(metrics_doc)

    print(f"✅ {len(metrics_docs)} documents de métriques créés pour le reporting des ventes.")
    return metrics_docs