import os
from dotenv import load_dotenv
import requests
import json
from datetime import datetime

# Chargement des variables d'env
load_dotenv()

#Configuration du connecteur 
url = os.getenv("ODOO_URL")
db = os.getenv("ODOO_DB")
username = os.getenv("ODOO_USERNAME")
password = os.getenv("ODOO_PASSWORD")

class FlexibleOdooConnector:
    def __init__(self):
        self.uid = None
        self.cache = {}
        self.all_data = {}

        self.models_config = {
            "sale.order": {
                "fields": ["id", "name", "partner_id", "amount_total", "state", "date_order", "user_id", "team_id", "company_id"],
                "limit": None,
                "relations": ["partner_id", "user_id", "team_id", "company_id"]
            },
            "res.partner": {
                "fields": ["id", "name", "email", "is_company", "country_id"],
                "limit": None,
                "relations": ["country_id"]
            },
            "res.users": {
                "fields": ["id", "name", "login", "email", "company_id"],
                "limit": None,
                "relations": ["company_id"]
            },
            "res.company": {
                "fields": ["id", "name", "country_id"],
                "limit": None,
                "relations": ["country_id"]
            },
            "res.country": {
                "fields": ["id", "name", "code"],
                "limit": None,
                "relations": []
            },
            "crm.team": {
                "fields": ["id", "name", "user_id", "company_id","invoiced_target"],
                "limit": None,
                "relations": ["user_id", "company_id"]
            },
        }

    def authenticate(self):
        payload = {
            "jsonrpc": "2.0", "method": "call",
            "params": {"service": "common", "method": "login", "args": [db, username, password]},
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
        if domain is None:
            domain = []
        payload = {
            "jsonrpc": "2.0", "method": "call",
            "params": {
                "service": "object", "method": "execute_kw",
                "args": [
                    db, self.uid, password, model, "search_read", [domain],
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

    def load_all_data(self):
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