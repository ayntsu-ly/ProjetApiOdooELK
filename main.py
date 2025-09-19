import sys
import time
from datetime import datetime
from collections import Counter
import json
import copy

from odoo_connector import FlexibleOdooConnector
from data_processor import create_universal_documents
from data_loader import send_to_logstash

# --- Paramètres ---
REFRESH_INTERVAL = 2 # secondes entre chaque cycle de mise à jour

def validate_data_quality(documents):
    """Valide la qualité des données avant envoi."""
    print("\n🔍 === VALIDATION DE LA QUALITÉ DES DONNÉES ===")
    
    issues = []
    sales_orders = [d for d in documents if d.get('source_model') == 'sale.order']
    
    negative_amounts = [d for d in sales_orders if d.get('amount_total', 0) < 0]
    if negative_amounts:
        issues.append(f"⚠️ {len(negative_amounts)} commandes avec montants négatifs")
    
    missing_dates = [d for d in sales_orders if not d.get('create_date')]
    if missing_dates:
        issues.append(f"⚠️ {len(missing_dates)} commandes sans date")
    
    no_team = [d for d in sales_orders if d.get('team_name') in [None, '', 'Non assignée']]
    if no_team:
        issues.append(f"⚠️ {len(no_team)} commandes sans équipe assignée")
    
    no_target = [d for d in sales_orders if d.get('team_invoiced_target', 0) <= 0]
    if no_target:
        issues.append(f"⚠️ {len(no_target)} commandes sans objectif d'équipe défini")
    
    if issues:
        print("🔍 Problèmes détectés :")
        for issue in issues:
            print(f"   {issue}")
        print("   → Ces données seront tout de même envoyées, mais vérifiez votre configuration Odoo")
    else:
        print("✅ Qualité des données validée")
    
    # Statistiques
    print(f"\n📊 Statistiques des données :")
    print(f"   • Total documents : {len(documents)}")
    print(f"   • Commandes de vente : {len(sales_orders)}")
    if sales_orders:
        total_amount = sum(d.get('amount_total', 0) for d in sales_orders)
        print(f"   • Montant total des ventes : {total_amount:,.2f}€")
        teams = Counter(d.get('team_name', 'Non assignée') for d in sales_orders)
        print(f"   • Équipes actives : {len(teams)}")
        states = Counter(d.get('state', 'unknown') for d in sales_orders)
        print(f"   • États des commandes : {dict(states)}")
    
    return True

def detect_changes(prev_docs_dict, current_docs):
    """Retourne les ajouts, modifications et suppressions."""
    current_docs_dict = {d['source_id']: d for d in current_docs}
    
    added = [d for sid, d in current_docs_dict.items() if sid not in prev_docs_dict]
    removed = [d for sid, d in prev_docs_dict.items() if sid not in current_docs_dict]
    
    modified = []
    for sid, doc in current_docs_dict.items():
        if sid in prev_docs_dict and doc != prev_docs_dict[sid]:
            modified.append(doc)
    
    return added, modified, removed

def main():
    print("🚀 === CONNECTEUR ODOO EN TEMPS RÉEL OPTIMISÉ POUR GROS VOLUMES ===")
    connector = FlexibleOdooConnector()
    if not connector.authenticate():
        print("❌ Échec de l'authentification. Arrêt du script.")
        sys.exit(1)
    
    prev_docs_dict = dict()  # dictionnaire des documents précédemment traités
    
    try:
        while True:
            start_time = datetime.now()
            print(f"\n🔄 Récupération des données Odoo - {start_time}")
            
            total_loaded = connector.load_all_data()  # sans offset/limit
            if total_loaded == 0:
                print("⚠️ Aucune donnée récupérée dans ce cycle.")
                time.sleep(REFRESH_INTERVAL)
                continue
            
            # Création des documents universels
            universal_docs = create_universal_documents(connector.all_data, connector.models_config)
            if not universal_docs:
                print("⚠️ Aucun document universel créé dans ce cycle.")
                time.sleep(REFRESH_INTERVAL)
                continue
            
            # Détecter ajouts, modifications et suppressions
            added, modified, removed = detect_changes(prev_docs_dict, universal_docs)
            
            if not added and not modified and not removed:
                print("ℹ️ Pas de changement détecté.")
            else:
                print(f"✅ Changements détectés : +{len(added)} / ~{len(modified)} / -{len(removed)}")
                # Validation
                validate_data_quality(added + modified)
                # Envoi à Logstash
                send_to_logstash(added + modified + removed, connector.models_config, clean_before_send=False)
            
            # Mettre à jour le dictionnaire de référence
            prev_docs_dict = {d['source_id']: copy.deepcopy(d) for d in universal_docs}
            
            # Pause avant le prochain cycle
            print(f"💤 Attente {REFRESH_INTERVAL}s avant le prochain cycle...")
            time.sleep(REFRESH_INTERVAL)
    
    except KeyboardInterrupt:
        print("\n⚠️ Script interrompu par l'utilisateur.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Erreur inattendue: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
