import requests
import json
import socket
import sys
from datetime import datetime
import time
from collections import defaultdict
from collections import Counter

url = "https://lab-odoo.europ-alu.com/jsonrpc"
db = "europ-alu"
username = "direction@vertec.mg"
password = "1234"

class FlexibleOdooConnector:
    def __init__(self):
        self.uid = None
        self.cache = {}
        self.relations_map = {}
        self.all_data = {}
        
        # Configuration des modèles à récupérer avec leurs relations
        self.models_config = {
            "sale.order": {
                "fields": ["id", "name", "partner_id", "amount_total", "state", "date_order", "user_id", "team_id", "company_id"],
                "limit": 1142,
                "relations": ["partner_id", "user_id", "team_id", "company_id"]
            },
            "sale.order.line": {
                "fields": ["id", "order_id", "product_id", "product_uom_qty", "price_unit", "price_subtotal", "discount"],
                "limit": 1142,
                "relations": ["order_id", "product_id"]
            },
            "purchase.order": {
                "fields": ["id", "name", "partner_id", "state", "date_order", "amount_total", "user_id", "company_id"],
                "limit": 500,
                "relations": ["partner_id", "user_id", "company_id"]
            },
            "purchase.order.line": {
                "fields": ["id", "order_id", "product_id", "product_qty", "price_unit", "price_subtotal"],
                "limit": 1000,
                "relations": ["order_id", "product_id"]
            },
            "product.template": {
                "fields": ["id", "name", "categ_id", "list_price", "default_code", "sage_ref", "company_id", "uom_id"],
                "limit": 1000,
                "relations": ["categ_id", "company_id", "uom_id"]
            },
            "product.product": {
                "fields": ["id", "product_tmpl_id", "default_code", "barcode"],
                "limit": 1000,
                "relations": ["product_tmpl_id"]
            },
            "product.category": {
                "fields": ["id", "name", "parent_id", "complete_name"],
                "limit": 200,
                "relations": ["parent_id"]
            },
            "res.partner": {
                "fields": ["id", "name", "email", "phone", "is_company", "customer_rank", "supplier_rank", "country_id", "category_id"],
                "limit": 500,
                "relations": ["country_id", "parent_id"]
            },
            "res.users": {
                "fields": ["id", "name", "login", "email", "company_id", "partner_id"],
                "limit": 200,
                "relations": ["company_id", "partner_id"]
            },
            "res.company": {
                "fields": ["id", "name", "country_id", "currency_id"],
                "limit": 50,
                "relations": ["country_id", "currency_id"]
            },
            "res.country": {
                "fields": ["id", "name", "code"],
                "limit": 300,
                "relations": []
            },
            "stock.quant": {
                "fields": ["id", "product_id", "inventory_quantity", "location_id", "lot_id", "company_id"],
                "limit": 1000,
                "relations": ["product_id", "location_id", "lot_id", "company_id"]
            },
            "stock.location": {
                "fields": ["id", "name", "location_id", "usage", "company_id"],
                "limit": 200,
                "relations": ["location_id", "company_id"]
            },
            "crm.team": {
                "fields": ["id", "name", "user_id", "company_id"],
                "limit": 100,
                "relations": ["user_id", "company_id"]
            },
            "account.move": {
                "fields": ["id", "name", "partner_id", "amount_total", "state", "move_type", "invoice_date", "company_id"],
                "limit": 1000,
                "relations": ["partner_id", "company_id"]
            },
            "account.move.line": {
                "fields": ["id", "move_id", "product_id", "quantity", "price_unit", "price_subtotal"],
                "limit": 1000,
                "relations": ["move_id", "product_id"]
            }
        }

    def authenticate(self):
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
            response = requests.post(url, json=payload, timeout=15).json()
            uid = response.get("result")
            
            if not uid:
                print("Erreur d'authentification:", response.get("error"))
                return None
                
            print("UID:", uid)
            self.uid = uid
            return uid
        except Exception as e:
            print(f"Erreur lors de l'authentification: {e}")
            return None

    def fetch_records(self, model, domain=None, fields=None, limit=None):
        """Récupère des enregistrements d'un modèle"""
        if domain is None:
            domain = []
        
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    db,
                    self.uid,
                    password,
                    model,
                    "search_read",
                    [domain],
                    {"fields": fields, "limit": limit} if fields or limit else {}
                ],
            },
            "id": model,
        }

        try:
            response = requests.post(url, json=payload, timeout=30).json()
            
            if "error" in response:
                print(f"❌ Erreur pour le modèle {model}: {response['error']}")
                return []
                
            result = response.get("result", [])
            print(f"   📊 {model}: {len(result)} enregistrements récupérés")
            return result
            
        except Exception as e:
            print(f"❌ Erreur lors de la récupération de {model}: {e}")
            return []

    def extract_id_from_many2one(self, field_value):
        """Extrait l'ID d'un champ Many2one"""
        if isinstance(field_value, list) and len(field_value) == 2:
            return field_value[0]
        elif isinstance(field_value, int):
            return field_value
        return None

    def extract_name_from_many2one(self, field_value):
        """Extrait le nom d'un champ Many2one"""
        if isinstance(field_value, list) and len(field_value) == 2:
            return field_value[1]
        return None

    def load_all_data(self):
        """Charge toutes les données des modèles configurés"""
        print("=== Chargement de toutes les données ===")
        total_records = 0
        
        for model_name, config in self.models_config.items():
            print(f"🔄 Chargement de {model_name}...")
            
            try:
                records = self.fetch_records(
                    model_name,
                    fields=config["fields"],
                    limit=config.get("limit")
                )
                
                # Stocker les données dans un dictionnaire indexé par ID
                self.all_data[model_name] = {}
                for record in records:
                    self.all_data[model_name][record['id']] = record
                
                total_records += len(records)
                print(f"✅ {model_name}: {len(records)} enregistrements stockés")
                
            except Exception as e:
                print(f"❌ Erreur lors du chargement de {model_name}: {e}")
                self.all_data[model_name] = {}
        
        print(f"\n📊 TOTAL CHARGÉ: {total_records} enregistrements")
        return total_records

    def resolve_relations(self, model_name, record, prefix="", depth=0):
        """Résout récursivement les relations d'un enregistrement."""
        resolved_data = {}
        
        if depth > 2:
            return resolved_data
        
        config = self.models_config.get(model_name, {})
        relations = config.get("relations", [])
        
        for relation_field in relations:
            field_value = record.get(relation_field)
            if field_value and isinstance(field_value, (list, int)):
                related_id = self.extract_id_from_many2one(field_value)
                
                if related_id:
                    target_model = self.get_target_model_for_field(model_name, relation_field)
                    
                    if target_model and target_model in self.all_data and related_id in self.all_data[target_model]:
                        related_record = self.all_data[target_model][related_id]
                        relation_prefix = f"{prefix}{relation_field.replace('_id', '')}_"
                        
                        resolved_data[f"{relation_prefix}id"] = related_id
                        resolved_data[f"{relation_prefix}name"] = self.extract_name_from_many2one(field_value)
                        
                        nested_resolved = self.resolve_relations(
                            target_model, 
                            related_record, 
                            relation_prefix, 
                            depth + 1
                        )
                        resolved_data.update(nested_resolved)
        
        return resolved_data

    def get_target_model_for_field(self, model_name, field_name):
        """Détermine le modèle cible pour un champ de relation"""
        # Mapping des champs vers les modèles cibles
        field_model_mapping = {
            "partner_id": "res.partner",
            "user_id": "res.users",
            "company_id": "res.company",
            "country_id": "res.country",
            "categ_id": "product.category",
            "parent_id": {
                "res.partner": "res.partner",
                "product.category": "product.category",
                "stock.location": "stock.location"
            },
            "product_id": {
                "sale.order.line": "product.product",
                "purchase.order.line": "product.product",
                "stock.quant": "product.product",
                "account.move.line": "product.product"
            },
            "product_tmpl_id": "product.template",
            "order_id": {
                "sale.order.line": "sale.order",
                "purchase.order.line": "purchase.order"
            },
            "move_id": "account.move",
            "location_id": "stock.location",
            "team_id": "crm.team",
            "currency_id": "res.currency",
            "uom_id": "uom.uom"
        }
        
        mapping = field_model_mapping.get(field_name)
        if isinstance(mapping, dict):
            return mapping.get(model_name)
        return mapping
    
    def create_universal_documents(self):
        """Crée des documents universels en enrichissant les documents d'origine."""
        print("\n=== Création des documents universels ===")
        universal_documents = []
        
        for model_name, records_dict in self.all_data.items():
            if not records_dict:
                print(f"⚠️  Aucune donnée pour {model_name}, skip...")
                continue
            
            print(f"🔄 Traitement de {model_name}...")
            
            for record_id, record in records_dict.items():
                try:
                    # Étape 1 : Créer le document de base avec les champs d'origine
                    universal_doc = {
                        "@timestamp": datetime.now().isoformat(),
                        "document_type": f"{model_name.replace('.', '_')}_analysis",
                        "source_model": model_name,
                        "source_id": record_id,
                        "odoo_database": db,
                        "source": "odoo-flexible-connector",
                        **record
                    }
                    
                    # Étape 2 : Enrichir le document avec les données des relations
                    resolved_data = self.resolve_relations(model_name, record)
                    universal_doc.update(resolved_data)
                    
                    universal_documents.append(universal_doc)
                
                except Exception as e:
                    print(f"❌ Erreur lors du traitement de {model_name} ID {record_id}: {e}")
            
            print(f"✅ {model_name}: {len([doc for doc in universal_documents if doc['source_model'] == model_name])} documents créés")
        
        print(f"\n📊 TOTAL: {len(universal_documents)} documents universels créés")
        return universal_documents

    def create_aggregated_metrics(self, universal_docs):
        """Crée des métriques agrégées pour toutes les entités importantes."""
        print("\n=== Calcul des métriques agrégées ===")
        metrics_docs = []

        # 1. Préparer les dictionnaires de métriques avec toutes les entités
        category_metrics = defaultdict(lambda: {
            'sales_total': 0, 'purchases_total': 0, 'stock_total': 0,
            'products_count': set(), 'orders_count': set(), 'margin': 0
        })
        all_categories = self.all_data.get('product.category', {}).values()
        for cat_data in all_categories:
            category_name = cat_data.get('complete_name', cat_data.get('name', 'Tous'))
            category_metrics[category_name]
        if 'Tous' not in category_metrics:
            category_metrics['Tous']

        partner_metrics = defaultdict(lambda: {
            'sales_total': 0, 'purchases_total': 0, 'orders_count': set(),
            'invoices_total': 0, 'is_company': None, 'balance': 0
        })
        all_partners = self.all_data.get('res.partner', {})
        for partner_data in all_partners.values():
            partner_name = partner_data.get('name', 'Inconnu')
            partner_metrics[partner_name]

        user_metrics = defaultdict(lambda: {
            'sales_total': 0, 'orders_count': set(), 'customers_count': set(), 'avg_order_value': 0
        })
        all_users = self.all_data.get('res.users', {})
        for user_data in all_users.values():
            user_name = user_data.get('name', 'Inconnu')
            user_metrics[user_name]

        company_metrics = defaultdict(lambda: {
            'sales_total': 0, 'purchases_total': 0, 'invoices_total': 0, 'balance': 0
        })
        all_companies = self.all_data.get('res.company', {})
        for company_data in all_companies.values():
            company_name = company_data.get('name', 'Inconnue')
            company_metrics[company_name]
        
        sales_team_metrics = defaultdict(lambda: {
            'sales_total': 0, 'orders_count': set(), 'customers_count': set()
        })
        all_sales_teams = self.all_data.get('crm.team', {})
        for team_data in all_sales_teams.values():
            team_name = team_data.get('name', 'Non assignée')
            sales_team_metrics[team_name]

        # 🆕 Le dictionnaire des métriques par équipe, région ET état
        team_region_metrics = defaultdict(lambda: {
            'sales_total': 0, 'orders_count': set(), 'customers_count': set()
        })
        
        # 2. Calculer les métriques en parcourant les documents universels
        for doc in universal_docs:
            source_model = doc.get('source_model')
            
            # --- Ventes (Sale Order) ---
            if source_model == 'sale.order':
                amount_total = doc.get('amount_total', 0)
                order_id = doc.get('source_id')
                order_state = doc.get('state', 'unknown')
                
                # Récupérer les informations de la commande
                partner_name = doc.get('partner_name', 'Inconnu')
                user_name = doc.get('user_name', 'Inconnu')
                company_name = doc.get('company_name', 'Inconnue')
                team_name = doc.get('team_name', 'Non assignée')

                # Récupérer le pays du partenaire pour la métrique par région
                partner_id = self.extract_id_from_many2one(doc.get('partner_id'))
                partner_doc = self.all_data.get('res.partner', {}).get(partner_id)
                partner_country_name = partner_doc.get('country_name', 'Non spécifié') if partner_doc else 'Non spécifié'

                # Agrégation par partenaire, vendeur, entreprise et équipe (mis à jour pour utiliser amount_total)
                partner_metrics[partner_name]['sales_total'] += amount_total
                partner_metrics[partner_name]['orders_count'].add(order_id)

                user_metrics[user_name]['sales_total'] += amount_total
                user_metrics[user_name]['orders_count'].add(order_id)
                user_metrics[user_name]['customers_count'].add(partner_name)

                company_metrics[company_name]['sales_total'] += amount_total

                sales_team_metrics[team_name]['sales_total'] += amount_total
                sales_team_metrics[team_name]['orders_count'].add(order_id)
                sales_team_metrics[team_name]['customers_count'].add(partner_name)

                # Agrégation par équipe, par région et par état
                key = (team_name, partner_country_name, order_state)
                team_region_metrics[key]['sales_total'] += amount_total
                team_region_metrics[key]['orders_count'].add(order_id)
                team_region_metrics[key]['customers_count'].add(partner_name)
            
            # --- Ventes par ligne de commande pour le calcul des totaux par catégorie ---
            # NOTE: On garde cette partie pour le `sales_total` par catégorie, car elle est par produit.
            # Cependant, le chiffre global de vente `sales_total` ne sera pas le `amount_total`
            # car il ne tient pas compte des taxes et frais. C'est un compromis.
            elif source_model == 'sale.order.line':
                subtotal = doc.get('price_subtotal', 0)
                order_id = doc.get('order_id')
                
                category_full_name = doc.get('product_product_product_template_categ_name') or 'Tous'
                category_levels = category_full_name.split(' / ')
                if category_levels[0] != 'Tous': category_levels.insert(0, 'Tous')
                for i in range(len(category_levels)):
                    current_level_name = ' / '.join(category_levels[:i+1])
                    category_metrics[current_level_name]['sales_total'] += subtotal
                    if order_id: category_metrics[current_level_name]['orders_count'].add(order_id)

            # --- Achats (Purchase Order Line) ---
            elif source_model == 'purchase.order.line':
                # ... (le code pour les achats est inchangé) ...
                subtotal = doc.get('price_subtotal', 0)
                order_id = doc.get('order_id')
                category_full_name = doc.get('product_product_product_template_categ_name') or 'Tous'
                category_levels = category_full_name.split(' / ')
                if category_levels[0] != 'Tous': category_levels.insert(0, 'Tous')
                for i in range(len(category_levels)):
                    current_level_name = ' / '.join(category_levels[:i+1])
                    category_metrics[current_level_name]['purchases_total'] += subtotal

                partner_name = doc.get('order_partner_name', 'Inconnu')
                company_name = doc.get('order_company_name', 'Inconnue')
                
                partner_metrics[partner_name]['purchases_total'] += subtotal
                if order_id: partner_metrics[partner_name]['orders_count'].add(order_id)
                company_metrics[company_name]['purchases_total'] += subtotal
                
            # --- Stock (Stock Quant) ---
            elif source_model == 'stock.quant':
                # ... (le code pour le stock est inchangé) ...
                quantity = doc.get('inventory_quantity', 0)
                product_data = doc.get('product_id')
                product_id = self.extract_id_from_many2one(product_data)
                category_full_name = doc.get('product_product_product_template_categ_name') or 'Tous'
                if product_id:
                    category_levels = category_full_name.split(' / ')
                    if category_levels[0] != 'Tous': category_levels.insert(0, 'Tous')
                    for i in range(len(category_levels)):
                        current_level_name = ' / '.join(category_levels[:i+1])
                        category_metrics[current_level_name]['stock_total'] += quantity
                        category_metrics[current_level_name]['products_count'].add(product_id)

            # --- Partenaires (Res Partner) ---
            elif source_model == 'res.partner':
                # ... (le code pour les partenaires est inchangé) ...
                partner_name = doc.get('name', 'Inconnu')
                is_company = doc.get('is_company')
                if partner_name in partner_metrics:
                    partner_metrics[partner_name]['is_company'] = is_company

        # 3. Créer les documents de métriques finaux à partir des dictionnaires complets
        # ... (cette partie reste inchangée et utilise les dictionnaires remplis dans l'étape 2) ...
        # Documents par catégorie (existant)
        for category_name, metrics in category_metrics.items():
            metrics_doc = {
                "@timestamp": datetime.now().isoformat(),
                "document_type": "category_metrics", "metric_type": "category_analysis", "odoo_database": db,
                "source": "odoo-flexible-connector", "category_name": category_name,
                "sales_total": metrics['sales_total'], "purchases_total": metrics['purchases_total'],
                "stock_total": metrics['stock_total'], "products_count": len(metrics['products_count']),
                "orders_count": len(metrics['orders_count']), "margin": metrics['sales_total'] - metrics['purchases_total']
            }
            metrics_docs.append(metrics_doc)

        # Documents par partenaire (existant)
        for partner_name, metrics in partner_metrics.items():
            metrics_doc = {
                "@timestamp": datetime.now().isoformat(),
                "document_type": "partner_metrics", "metric_type": "partner_analysis", "odoo_database": db,
                "source": "odoo-flexible-connector", "partner_name": partner_name,
                "sales_total": metrics['sales_total'], "purchases_total": metrics['purchases_total'],
                "orders_count": len(metrics['orders_count']), "balance": metrics['sales_total'] - metrics['purchases_total'],
                "is_company": metrics.get('is_company')
            }
            metrics_docs.append(metrics_doc)

        # Documents par utilisateur (existant)
        for user_name, metrics in user_metrics.items():
            orders_count = len(metrics['orders_count'])
            avg_order_value = metrics['sales_total'] / orders_count if orders_count else 0
            metrics_doc = {
                "@timestamp": datetime.now().isoformat(),
                "document_type": "user_metrics", "metric_type": "sales_performance", "odoo_database": db,
                "source": "odoo-flexible-connector", "user_name": user_name,
                "sales_total": metrics['sales_total'], "orders_count": orders_count,
                "customers_count": len(metrics['customers_count']), "avg_order_value": avg_order_value
            }
            metrics_docs.append(metrics_doc)

        # Documents par société (existant)
        for company_name, metrics in company_metrics.items():
            metrics_doc = {
                "@timestamp": datetime.now().isoformat(),
                "document_type": "company_metrics", "metric_type": "company_performance", "odoo_database": db,
                "source": "odoo-flexible-connector", "company_name": company_name,
                "sales_total": metrics['sales_total'], "purchases_total": metrics['purchases_total'],
                "balance": metrics['sales_total'] - metrics['purchases_total']
            }
            metrics_docs.append(metrics_doc)

        # Documents par équipe de vente (existant, mais avec des clients en plus)
        for team_name, metrics in sales_team_metrics.items():
            orders_count = len(metrics['orders_count'])
            avg_order_value = metrics['sales_total'] / orders_count if orders_count else 0
            metrics_doc = {
                "@timestamp": datetime.now().isoformat(),
                "document_type": "sales_team_metrics", "metric_type": "sales_performance", "odoo_database": db,
                "source": "odoo-flexible-connector", "sales_team_name": team_name,
                "sales_total": metrics['sales_total'], "orders_count": orders_count,
                "customers_count": len(metrics['customers_count']), "avg_order_value": avg_order_value
            }
            metrics_docs.append(metrics_doc)

        # 🆕 Documents par équipe, par région et par état
        for (team_name, region_name, state), metrics in team_region_metrics.items():
            orders_count = len(metrics['orders_count'])
            avg_order_value = metrics['sales_total'] / orders_count if orders_count else 0
            metrics_doc = {
                "@timestamp": datetime.now().isoformat(),
                "document_type": "team_region_metrics", 
                "metric_type": "sales_performance_by_region", 
                "odoo_database": db,
                "source": "odoo-flexible-connector", 
                "sales_team_name": team_name,
                "region_name": region_name, 
                "state": state,
                "sales_total": metrics['sales_total'],
                "orders_count": orders_count, 
                "avg_order_value": avg_order_value
            }
            metrics_docs.append(metrics_doc)

        print(f"✅ {len(metrics_docs)} documents de métriques créés (incluant les entités sans activité)")
        return metrics_docs
    
    def send_to_logstash(self, data, batch_size=500):
        """Envoi les données à Logstash."""
        logstash_host = "localhost"
        logstash_port = 5000

        total_records = len(data)
        if total_records == 0:
            print("⚠️  Aucune donnée à envoyer")
            return True

        print(f"🚀 Envoi de {total_records} enregistrements à Logstash...")

        # compteur par type
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

            # 📊 Résumé par type
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

    def save_backup(self, data, filename=None):
        """Sauvegarde locale des données en JSON"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"odoo_universal_backup_{timestamp}.json"
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            print(f"💾 Sauvegarde créée: {filename}")
            return True
        except Exception as e:
            print(f"❌ Erreur lors de la sauvegarde: {e}")
            return False

def main():
    print("🚀 === CONNECTEUR ODOO UNIVERSEL ET FLEXIBLE - V2 ===")
    start_time = datetime.now()
    
    connector = FlexibleOdooConnector()
    
    # 1. Authentification
    print("\n🔐 === AUTHENTIFICATION ===")
    if not connector.authenticate():
        print("❌ Échec de l'authentification. Arrêt du script.")
        sys.exit(1)
    
    # 2. Chargement de toutes les données
    print(f"\n📥 === CHARGEMENT DES DONNÉES ===")
    total_loaded = connector.load_all_data()
    
    if total_loaded == 0:
        print("❌ Aucune donnée chargée. Vérifiez votre connexion Odoo.")
        sys.exit(1)
    
    # 3. Création des documents universels
    print(f"\n⚙️  === CRÉATION DES DOCUMENTS UNIVERSELS ===")
    universal_docs = connector.create_universal_documents()

    types_counter = Counter(doc['document_type'] for doc in universal_docs)
    print("📊 Types de documents universels créés :")
    for doc_type, count in types_counter.items():
        print(f"   {doc_type}: {count}")
    
    if not universal_docs:
        print("❌ Aucune donnée universelle créée. Arrêt du script.")
        sys.exit(1)

    print("\n🔍 Premier document universel créé (test) :")
    print(json.dumps(universal_docs[0], indent=2, ensure_ascii=False))     
    
    # 4. Création des métriques agrégées
    print(f"\n📊 === CALCUL DES MÉTRIQUES ===")
    metrics_docs = connector.create_aggregated_metrics(universal_docs)
    
    # 5. Combiner tous les documents
    all_documents = universal_docs + metrics_docs
    
    # 6. Affichage des résultats
    print(f"\n📈 === APERÇU DES DONNÉES UNIVERSELLES ===")
    doc_types = {}
    for record in all_documents:
        doc_type = record.get("document_type", "unknown")
        doc_types[doc_type] = doc_types.get(doc_type, 0) + 1
    
    for doc_type, count in sorted(doc_types.items()):
        print(f"   📋 {doc_type}: {count} enregistrements")
    
    print(f"\n🎯 TOTAL: {len(all_documents)} enregistrements prêts")
    
    # 7. Sauvegarde locale
    print("\n💾 === SAUVEGARDE LOCALE ===")
    connector.save_backup(all_documents)
    
    # 8. Envoi à Logstash
    print(f"\n🚀 === ENVOI À LOGSTASH ===")
    success = connector.send_to_logstash(all_documents)
    
    # 9. Résumé
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    print(f"\n🏁 === RÉSUMÉ FINAL ===")
    print(f"⏱️  Durée totale: {duration:.2f} secondes")
    print(f"📊 Documents traités: {len(all_documents)}")
    print(f"📥 Types de documents: {len(doc_types)}")
    
    if success:
        print("\n✅ 🎉 SCRIPT EXÉCUTÉ AVEC SUCCÈS ! 🎉")
        print("\n🎯 ANALYSES POSSIBLES DANS KIBANA:")
        print("   • 🛒 Ventes par catégorie, client, vendeur, pays, entreprise")
        print("   • 📈 Performance des vendeurs par région/produit")
        print("   • 💰 Analyse des marges par catégorie/client")
        print("   • 📅 Tendances temporelles multi-dimensionnelles")
        print("   • 📦 Stock par catégorie/localisation/entreprise")
        print("   • 🤝 Analyse des fournisseurs et clients")
        print("   • 🎯 Métriques de performance automatiques")
        print("\n🚀 VOTRE SYSTÈME EST MAINTENANT 100% OPÉRATIONNEL !")
    else:
        print("⚠️  Script terminé avec des erreurs d'envoi.")
        print("💡 Vérifiez que Logstash est démarré et écoute sur le port 5000.")
        
    print(f"\n🔍 Pour vérifier vos données dans Elasticsearch:")
    print(f"   curl -X GET 'localhost:9200/_cat/indices?v'")
    print(f"   curl -X GET 'localhost:9200/logstash-*/_count?pretty'")

if __name__ == "__main__":
    main()