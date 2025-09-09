import sys
from datetime import datetime
from collections import Counter
import json

from odoo_connector import FlexibleOdooConnector
from data_processor import create_universal_documents
from data_loader import send_to_logstash, save_backup


def validate_data_quality(documents):
    """Valide la qualité des données avant envoi"""
    print("\n🔍 === VALIDATION DE LA QUALITÉ DES DONNÉES ===")
    
    issues = []
    sales_orders = [d for d in documents if d.get('source_model') == 'sale.order']
    
    # Vérifier les montants négatifs ou nuls suspects
    negative_amounts = [d for d in sales_orders if d.get('amount_total', 0) < 0]
    if negative_amounts:
        issues.append(f"⚠️ {len(negative_amounts)} commandes avec montants négatifs")
    
    # Vérifier les dates manquantes
    missing_dates = [d for d in sales_orders if not d.get('date_order')]
    if missing_dates:
        issues.append(f"⚠️ {len(missing_dates)} commandes sans date")
    
    # Vérifier les équipes assignées
    no_team = [d for d in sales_orders if d.get('team_name') in [None, '', 'Non assignée']]
    if no_team:
        issues.append(f"⚠️ {len(no_team)} commandes sans équipe assignée")
    
    # Vérifier les objectifs d'équipe
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
    
    # Afficher des statistiques utiles
    print(f"\n📊 Statistiques des données :")
    print(f"   • Total documents : {len(documents)}")
    print(f"   • Commandes de vente : {len(sales_orders)}")
    
    if sales_orders:
        total_amount = sum(d.get('amount_total', 0) for d in sales_orders)
        print(f"   • Montant total des ventes : {total_amount:,.2f}€")
        
        # Statistiques par équipe
        teams = Counter(d.get('team_name', 'Non assignée') for d in sales_orders)
        print(f"   • Équipes actives : {len(teams)}")
        
        # Statistiques par état
        states = Counter(d.get('state', 'unknown') for d in sales_orders)
        print(f"   • États des commandes : {dict(states)}")
    
    return True

def main():
    print("🚀 === CONNECTEUR ODOO POUR LE REPORTING COMMERCIAL - V4 SIMPLIFIÉ ===")
    start_time = datetime.now()
    
    try:
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
        print(f"\n⚙️ === CRÉATION DES DOCUMENTS UNIVERSELS ===")
        universal_docs = create_universal_documents(connector.all_data, connector.models_config)
        
        if not universal_docs:
            print("❌ Aucune donnée universelle créée. Arrêt du script.")
            sys.exit(1)
            
        print(f"✅ {len(universal_docs)} documents universels créés")
        
        # 3. Validation de la qualité
        validate_data_quality(universal_docs)
        
        # 4. Affichage d'un exemple de document
        print("\n🔍 === EXEMPLE DE DOCUMENT DE VENTE ===")
        sample_doc = next((doc for doc in universal_docs if doc.get('source_model') == 'sale.order'), None)
        if sample_doc:
            sample_display = {
                "document_type": sample_doc.get('document_type'),
                "source_model": sample_doc.get('source_model'),
                "source_id": sample_doc.get('source_id'),
                "amount_total": sample_doc.get('amount_total'),
                "partner_name": sample_doc.get('partner_name'),
                "team_name": sample_doc.get('team_name'),
                "team_invoiced_target": sample_doc.get('team_invoiced_target'),
                "year": sample_doc.get('year'),
                "month_name": sample_doc.get('month_name'),
                "state": sample_doc.get('state'),
                "state_label": sample_doc.get('state_label')
            }
            print(json.dumps(sample_display, indent=2, ensure_ascii=False))
        
        # 5. Sauvegarde et envoi à Logstash
        print("\n💾 === SAUVEGARDE LOCALE ===")
        backup_success = save_backup(universal_docs)
        
        print(f"\n🚀 === ENVOI À LOGSTASH ===")
        # La déduplication se fait automatiquement dans send_to_logstash()
        send_success = send_to_logstash(universal_docs, clean_before_send=True)
        
        # 6. Résumé final
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print(f"\n🏁 === RÉSUMÉ FINAL ===")
        print(f"⏱️ Durée totale: {duration:.2f} secondes")
        print(f"📊 Documents traités: {len(universal_docs)}")
        print(f"💾 Sauvegarde: {'✅ Réussie' if backup_success else '❌ Échouée'}")
        print(f"🚀 Envoi Logstash: {'✅ Réussi' if send_success else '❌ Échoué'}")
        
        if send_success:
            print("\n✅ 🎉 SCRIPT EXÉCUTÉ AVEC SUCCÈS ! 🎉")
            print("💡 Conseil : Attendez ~30 secondes avant de vérifier dans Kibana")
        else:
            print("\n❌ ÉCHEC DE L'EXÉCUTION DU SCRIPT.")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⚠️ Script interrompu par l'utilisateur")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Erreur inattendue: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()