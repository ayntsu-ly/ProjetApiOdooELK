import sys
from datetime import datetime
from collections import defaultdict, Counter
import json

from odoo_connector import FlexibleOdooConnector
from data_processor import create_universal_documents, create_aggregated_metrics
from data_loader import send_to_logstash

def deduplicate_documents(documents):
    """Supprime les doublons potentiels avant envoi"""
    seen_ids = set()
    unique_docs = []
    duplicates_count = 0
    
    for doc in documents:
        # Générer un ID temporaire pour la déduplication locale
        if doc.get('source_model') == 'sale.order':
            temp_id = f"sale_order_{doc.get('source_id')}"
        elif doc.get('document_type') == 'team_monthly_performance':
            team = doc.get('team_name', '').replace(' ', '_')
            year = doc.get('year', 'unknown')
            month = doc.get('month_name', 'unknown')
            temp_id = f"team_perf_{team}_{year}_{month}"
        elif doc.get('document_type') == 'user_metrics':
            user = doc.get('user_name', '').replace(' ', '_')
            temp_id = f"user_metrics_{user}"
        elif doc.get('document_type') == 'sales_team_metrics':
            team = doc.get('team_name', '').replace(' ', '_')
            temp_id = f"team_metrics_{team}"
        elif doc.get('document_type') == 'order_state_metrics':
            state = doc.get('state', 'unknown')
            temp_id = f"state_metrics_{state}"
        elif doc.get('document_type') == 'team_state_metrics':
            team = doc.get('team_name', '').replace(' ', '_')
            state = doc.get('state', 'unknown')
            temp_id = f"team_state_{team}_{state}"
        else:
            temp_id = f"{doc.get('document_type', 'unknown')}_{doc.get('source_id', 'no_id')}"
        
        if temp_id not in seen_ids:
            seen_ids.add(temp_id)
            unique_docs.append(doc)
        else:
            duplicates_count += 1
            print(f"🔍 Doublon local détecté et supprimé: {temp_id}")
    
    if duplicates_count > 0:
        print(f"⚠️ {duplicates_count} doublons locaux supprimés")
    
    return unique_docs

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
    
    # Vérifier les métriques de performance
    perf_docs = [d for d in documents if d.get('document_type') == 'team_monthly_performance']
    no_target = [d for d in perf_docs if d.get('target_amount', 0) <= 0]
    if no_target:
        issues.append(f"⚠️ {len(no_target)} périodes sans objectif défini")
    
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
    print(f"   • Documents de performance : {len(perf_docs)}")
    
    if sales_orders:
        total_amount = sum(d.get('amount_total', 0) for d in sales_orders)
        print(f"   • Montant total des ventes : {total_amount:,.2f}€")
    
    return True

def main():
    print("🚀 === CONNECTEUR ODOO POUR LE REPORTING COMMERCIAL - V3 ANTI-DOUBLONS ===")
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
        print(f"\n⚙️  === CRÉATION DES DOCUMENTS UNIVERSELS ===")
        universal_docs = create_universal_documents(connector.all_data, connector.models_config)
        
        if not universal_docs:
            print("❌ Aucune donnée universelle créée. Arrêt du script.")
            sys.exit(1)
            
        print(f"✅ {len(universal_docs)} documents universels créés")

        # 3. Création des métriques agrégées
        print(f"\n📊 === CALCUL DES MÉTRIQUES ===")
        metrics_docs = create_aggregated_metrics(universal_docs)
        print(f"✅ {len(metrics_docs)} documents de métriques créés")
        
        # 4. Combiner et dédupliquer
        print(f"\n🔄 === CONSOLIDATION DES DONNÉES ===")
        all_documents = universal_docs + metrics_docs
        print(f"📋 Total avant déduplication : {len(all_documents)} documents")
        
        # Déduplication locale
        unique_documents = deduplicate_documents(all_documents)
        print(f"✅ Total après déduplication : {len(unique_documents)} documents")
        
        # 5. Validation de la qualité
        validate_data_quality(unique_documents)
        
        # 6. Affichage d'un exemple de document
        print("\n🔍 === EXEMPLE DE DOCUMENT DE VENTE ===")
        sample_doc = next((doc for doc in unique_documents if doc.get('source_model') == 'sale.order'), None)
        if sample_doc:
            # Afficher seulement les champs importants pour éviter trop de verbosité
            sample_display = {
                "document_type": sample_doc.get('document_type'),
                "source_model": sample_doc.get('source_model'),
                "source_id": sample_doc.get('source_id'),
                "amount_total": sample_doc.get('amount_total'),
                "partner_name": sample_doc.get('partner_name'),
                "team_name": sample_doc.get('team_name'),
                "year": sample_doc.get('year'),
                "month_name": sample_doc.get('month_name'),
                "state": sample_doc.get('state')
            }
            print(json.dumps(sample_display, indent=2, ensure_ascii=False))
        
        
        print(f"\n🚀 === ENVOI À LOGSTASH ===")
        # L'option clean_before_send=True est cruciale pour éviter les doublons
        send_success = send_to_logstash(unique_documents, clean_before_send=True)
        
        # 8. Résumé final
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print(f"\n🏁 === RÉSUMÉ FINAL ===")
        print(f"⏱️  Durée totale: {duration:.2f} secondes")
        print(f"📊 Documents uniques traités: {len(unique_documents)}")
        print(f"🚀 Envoi Logstash: {'✅ Réussi' if send_success else '❌ Échoué'}")
        
        if send_success:
            print("\n✅ 🎉 SCRIPT EXÉCUTÉ AVEC SUCCÈS - AUCUN DOUBLON ! 🎉")
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