# Procédure de validation des données en deux étapes (5 novembre 2026)

## Étape 1 — Audit des prix, sans calcul LPPLS

Dès qu'un CSV de prix est chargé, Streamlit analyse les cours **quotidiens et hebdomadaires** à partir du parseur commun, sans modifier le fichier original. L'audit est mémorisé par contenu du fichier pour ne pas relancer inutilement le scan.

Critères initiaux (heuristiques, non preuves d'erreur) :
- Rendement quotidien absolu >= **50 %** ;
- Rendement hebdomadaire absolu >= **50 %** ;
- **8** cours hebdomadaires consécutifs identiques ;
- Intervalles de cours hebdomadaires manquants **à l'intérieur d'une série déjà cotée**, avec nombre de semaines indiqué (pas de confusion avec les périodes avant introduction en Bourse) ;
- `CRITICAL` lorsque le saut est >= +300 % ou <= -90 %, sinon `REVIEW`.

Le tableau renseigne le titre, la date, la fréquence, le cours précédent, le cours actuel, la variation en %, le nombre éventuel de semaines manquantes, le type et la gravité. Les alertes quotidiennes et hebdomadaires peuvent désigner **le même événement économique** et ne doivent pas être décomptées comme des événements distincts.

Ce filtre **ne certifie pas les séries ajustées**. Les valeurs manquantes, cours nuls ou opérations sur titres demandent éventuellement une vérification indépendante auprès du fournisseur ; les seuils proposés ne sont ni exhaustifs ni optimisés pour le backtest.

## Décisions disponibles

| Décision | Effet réel | Interprétation |
|---|---|---|
| `REVIEW` | Aucun effet, anomalie en attente | Autorisé uniquement après reconnaissance explicite des alertes critiques non résolues |
| `KEEP` | Cours conservés tels quels | Décision d'examen, pas preuve de validité économique |
| `EXCLUDE_BACKTEST_RETRO` | **Exclusion du titre entier uniquement du backtest**, sur toutes les dates | **Analyse de sensibilité rétrospective**, la classification LPPLS reste disponible |
| `EXCLUDE_ASSET_RETRO` | **Exclusion du titre entier sur toutes les dates**, dans le snapshot ET dans le backtest | **Analyse de sensibilité rétrospective**, non représentative d'un portefeuille historique sans anticipation |
| `BLOCK_ASOF` | Blocage de nouvelles positions **aux dates habituelles de rééquilibrage** une fois l'événement publié | Nécessite `reason`, `evidence` et `published_at`, sans liquidation hebdomadaire forcée ni modification rétroactive des rendements déjà subis |

Les choix autres que `REVIEW` exigent une justification. Pour `BLOCK_ASOF`, la date de publication ne peut pas être antérieure à l'anomalie qui a motivé l'action ; les publications ne sont pas vérifiées automatiquement. Si l'utilisateur a déjà une position lorsque le blocage devient actif, le moteur actuel ne la solde qu'à la **prochaine date ordinaire de décision**. Il ne faut pas prétendre que ce dispositif évite une variation déjà réalisée.

**Non implémenté volontairement** : retirer un cours isolé ou un intervalle de prix, créer une interpolation arbitraire ou liquider immédiatement une position à une date rétroactive. Ces actes nécessitent de définir la convention de rendement et de transaction : masquer un cours pourrait déplacer le choc d'une semaine à l'autre.

Le champ `exclude_backtest_retro` est une case à cocher dans l'interface, transcrite dans le registre comme `EXCLUDE_BACKTEST_RETRO`. L'exclusion commune au snapshot et au backtest est un **choix séparé** dans la liste d'actions. Aucun de ces choix n'efface la source originale.

## Registre CSV réutilisable

Le fichier `data_quality_decisions.csv` enregistre les champs suivants :

- `event_id` : SHA-256 tronqué d'une identité stable (actif, date, fréquence, type de signal) ;
- `price_fingerprint` : SHA-256 des éléments d'identité **et des deux cours comparés** ;
- `asset,date,frequency,kind,previous_price,observed_price,return_pct,gap_weeks,severity` ;
- `action,reason,evidence,published_at`.

À la prochaine importation, le moteur rapproche ce registre avec les alertes du nouveau fichier :
- `MATCH` : observation identique, décision réappliquée ;
- `CHANGED_PRICE_REVIEW` : mêmes actif et date mais prix révisés, décision antérieure **non réappliquée** ; confirmation explicite exigée pour une nouvelle décision ;
- `NEW` : nouvel événement, défaut `REVIEW` ;
- `NOT_DETECTED_IN_CURRENT_SOURCE` : ancien événement absent, non réappliqué.

Si aucune anomalie n'est détectée, le passage à la deuxième étape est direct. Si toutes les anomalies critiques ont une décision compatible, aucune confirmation supplémentaire n'est demandée. Si des alertes critiques restent `REVIEW`, Streamlit demande une reconnaissance explicite avant d'exécuter le LPPLS.

## Étape 2 — Analyses et backtest

Les deux analyses partent de **la même source originale** et de la même grille LPPLS. Elles peuvent toutefois recevoir des **univers explicitement différents** : une exclusion `BACKTEST_ONLY` retire une colonne du CSV backtest mais la conserve pour les estimations LPPLS et les diagnostics statistiques ; une exclusion `EXCLUDE_ASSET_RETRO` retire la colonne des deux CSV. Les différences sont recensées et publiées. Si `BLOCK_ASOF` est sélectionné et que le backtest est activé, les événements documentés sont transmis au filtre `block_documented`.

Aucune restriction supplémentaire n'est ajoutée à la grille LPPLS : elle reste **7×7×7 = 343**, identique pour snapshot et backtest. Les pondérations et stratégies antérieures sont conservées.

Une signature du fichier, des choix de qualité et des paramètres d'estimation évite d'afficher comme actuel un ZIP d'une exécution précédente.

## Nouveaux fichiers du ZIP

Tous les livrables historiques restent regroupés dans le ZIP unique. Le dossier `audit/` contient désormais :
- `data_quality_anomalies.csv` : anomalies détectées avant décision ;
- `data_quality_decisions.csv` : registre importable lors d'une prochaine exécution ;
- `snapshot_prices.csv` : **exact** CSV utilisé pour les estimations LPPLS et les diagnostics statistiques ;
- `backtest_prices.csv` : **exact** CSV utilisé pour les rendements et positions historiques ;
- `excluded_assets.csv` : titres retirés rétrospectivement ;
- `previous_rules_not_reapplied.csv` : anciennes décisions non reconnues dans la source actualisée.

Le dossier `donnees/source.csv` contient toujours le **fichier original inchangé**. `donnees/quality_events.csv` conserve, si nécessaire, le registre d'événements documentés utilisé au backtest. `manifest.json` enregistre la qualification de l'étude et le nombre d'anomalies.

Les résultats rétrospectifs et causaux ne sont **pas interchangeables** ; les différences de performances devront être documentées comme des analyses de sensibilité, notamment lorsqu'un titre est exclu à cause d'une variation découverte postérieurement.

## Tests et recette

Lancer localement `python -m pytest -q`, puis vérifier dans Streamlit :
1. Upload CSV, affichage immédiat des alertes sans démarrer le modèle LPPLS ;
2. Import d'un registre compatible, récupération des décisions, distinction des nouvelles anomalies ;
3. Révision d'une observation et absence de réapplication automatique ;
4. Checkbox d'exclusion du backtest seulement, puis choix distinct d'exclusion globale : contrôle des deux CSV et du libellé de sensibilité ;
5. `BLOCK_ASOF` avec source/date et contrôle des positions à la prochaine date de décision ;
6. ZIP comprenant l'original, le CSV réellement analysé et le registre, avec manifeste et empreintes corrects ;
7. Modification du CSV ou d'une décision : ne plus afficher le ZIP obsolète.

Les tests ciblés du module sont exécutables hors CI ; la recette Streamlit de bout en bout reste distincte de la validation du module d'audit.


### Correction du lancement de l'étape 2 (5 novembre 2026)

Le CSV `data_quality_decisions.csv` contient les choix de validation de **l'étape 1** ; le CSV `asset,published_at,action,source` correspond uniquement aux événements datés de blocage. Les deux formats sont maintenant détectés automatiquement. Si `data_quality_decisions.csv` est chargé dans l'option avancée destinée aux événements, l'interface le reconnaît et le réutilise comme registre de décisions, sans le transmettre comme événements.

S'il reste des alertes critiques `REVIEW`, une case de confirmation est placée **immédiatement au-dessus du bouton « Lancer l'analyse »**. Le bouton s'active après confirmation ; les alertes et les rendements demeurent inchangés et sont archivés. La validation de chaque événement n'est pas obligatoire pour exécuter une analyse exploratoire. En absence d'alerte critique, cette case ne bloque pas le lancement.

Les registres datés de blocage restent une option avancée ; lorsque ce registre est fourni au backtest, il active la politique `block_documented` pour les futures positions éligibles (sans effacer les rendements passés).
