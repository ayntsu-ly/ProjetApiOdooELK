import sys
from datetime import datetime
from collections import defaultdict, Counter
import json

from odoo_connector import FlexibleOdooConnector
from data_processor import create_universal_documents, create_aggregated_metrics
from data_loader import send_to_logstash, save_backup

def main():
    print("🚀 === CONNECTEUR ODOO POUR LE REPORTING COMMERCIAL - V2 ===")
    start_time = datetime.now()
    
    # 1. Authentification et chargement des données
    print("\n🔐 === AUTHENTIFICATION & CHARGEMENT DES DONNÉES ===")
    connector = FlexibleOdooConnector()
    if not connector.authenticate():
        print("❌ Échec de l'authentification. Arrêt du script.")
        sys.exit(1)
    
    total_loaded = connector.load_all_data()
    
    if total_loaded == 0:
        print("❌ Aucune donnée chargée. Vérifiez votre connexion Odoo.")
        sys.exit(1)
    
    # 2. Création des documents universels
    print(f"\n⚙️  === CRÉATION DES DOCUMENTS UNIVERSELS ===")
    universal_docs = create_universal_documents(connector.all_data, connector.models_config)
    
    if not universal_docs:
        print("❌ Aucune donnée universelle créée. Arrêt du script.")
        sys.exit(1)
        
    print("\n🔍 Exemple de document de vente (avec dimensions temporelles) :")
    sample_doc = next((doc for doc in universal_docs if doc.get('source_model') == 'sale.order'), None)
    if sample_doc:
        print(json.dumps(sample_doc, indent=2, ensure_ascii=False))

    # 3. Création des métriques agrégées
    print(f"\n📊 === CALCUL DES MÉTRIQUES ===")
    metrics_docs = create_aggregated_metrics(universal_docs)
    
    # 4. Combiner tous les documents
    all_documents = universal_docs + metrics_docs
    
    # 5. Sauvegarde et envoi à Logstash
    print("\n💾 === SAUVEGARDE LOCALE ===")
    save_backup(all_documents)
    
    print(f"\n🚀 === ENVOI À LOGSTASH ===")
    success = send_to_logstash(all_documents)
    
    # 6. Résumé
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    print(f"\n🏁 === RÉSUMÉ FINAL ===")
    print(f"⏱️  Durée totale: {duration:.2f} secondes")
    print(f"📊 Documents traités: {len(all_documents)}")
    
    if success:
        print("\n✅ 🎉 SCRIPT EXÉCUTÉ AVEC SUCCÈS ! 🎉")
    else:
        print("\n❌ ÉCHEC DE L'EXÉCUTION DU SCRIPT.")

if __name__ == "__main__":
    main()