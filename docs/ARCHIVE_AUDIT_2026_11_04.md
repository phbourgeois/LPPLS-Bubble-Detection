# Audit des archives LPPLS — 4 novembre 2026

## Portée et provenance

- Archives du projet : `lppls_outputs.zip` et `lppls_complete_notebooks_and_outputs.zip`.
- L'archive complète contient **6 notebooks**, `lppls_core.py`, un CSV synthétique, un fichier de dépendances et les résultats historiques.
- Les **6 sorties** de l'archive `lppls_outputs.zip` sont **identiques octet par octet** à celles de l'archive complète. Les empreintes sont dans `artifacts/historical_2026_02_27/SHA256_MANIFEST.json`.
- Contenu observé dans les CSV : **15 actifs**, 105 lignes d'estimations multi-fenêtres, dernière date **2026-02-27**. Les fichiers ne contiennent pas les NAV historiques de backtests.

## Différencier les notebooks

Les fichiers de `research/reproducible_2026_11_04/notebooks/` **ne sont pas les mêmes** que les fichiers historiquement récupérés sous `notebooks/`, même lorsque les noms coïncident. Ce sont des lanceurs courts qui importent le module `lppls_core.py`, et non des notebooks autonomes avec le moteur copié dans les cellules. Aucun des six notebooks du nouveau pack n'a de sorties de cellule enregistrées.

| Notebook nouveau | Rôle |
|---|---|
| `ds_lppls_pipeline.ipynb` | Snapshot multi-échelles et exports |
| `ds_lppls_pipeline_executed.ipynb` | Notebook prêt à exécuter, **non exécuté** |
| `ds_lppls_pipeline_with_backtest.ipynb` | Snapshot et backtest |
| `ds_lppls_pipeline_with_backtest_named.ipynb` | Variante avec contrôle des noms d'actifs |
| `ds_lppls_backtest_only.ipynb` | Backtest indépendant |
| `ds_lppls_validation.ipynb` | Contrôle des schémas de sorties (pas de validation scientifique) |

## Arbitrage et corrections

Le fichier `lppls_core.py` daté du pack de novembre 2026 est une **nouvelle implémentation autonome** du moteur LPPLS et du backtest, plus flexible sur l'import CSV et dotée d'un benchmark équipondéré. Elle ne remplace pas `src/lppls_bubble/legacy_engine.py` ni `src/lppls_bubble/backtest.py`, qui alimentent actuellement Streamlit.

L'exécution initiale du `lppls_core.py` de l'archive sur le CSV synthétique **échoue** à `DataFrame.std(min_count=13)` avec pandas 2.2.3 (argument non valide). Le dossier `research/` contient une copie d'origine inchangée et une copie corrigée avec **4 modifications documentées** dans son README.

Vérifications locales (sur le CSV synthétique fourni) : import, génération des **5 CSV de synthèse + PNG**, backtest à trois rééquilibrages, production des séries NAV et indicateurs. Les tests unitaires de régression (`tests/test_research_pack.py`) protègent la compatibilité pandas, le nombre de semaines valorisées et les empreintes des archives. Les tests historiques sur `Miscellanous.csv`/`SBF120.csv` restent impossibles sans les entrées d'origine.

## Réserves en aval

- Les deux implémentations **ne doivent pas être mélangées** ni leurs performances comparées sans protocole commun.
- Absence de preuve de significativité statistique ou d'utilité prédictive de la classification LPPLS.
- Les données brutes et les conventions financières (prix ajustés, devises, frais réels, crédit, dividendes, financement des shorts, biais de survivance) ne sont pas documentées dans les ZIP.
- La valorisation avec rendements manquants est différente : la version Streamlit peut refuser les positions détenues si le prix manque ; la nouvelle expérimentation documente une valorisation au dernier prix, potentiellement biaisée.
- Les outputs historiques ne sont pas **recalculés** dans cette opération ; ils sont archivés en l'état.
- Le dépôt est public ; contrôler les éventuels droits de redistribution de résultats dérivés de données fournisseurs avant toute diffusion externe.

## Crédits GitHub Actions

Aucun workflow créé ou déclenché. Tests locaux ; publication des seuls fichiers utiles dans un commit avec `[skip ci]`.
