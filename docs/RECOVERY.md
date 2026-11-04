# Inventaire de migration et journal des reserves

Date : 2026-11-04.

## Source verifiee

- `ds_lppls_pipeline.ipynb` : Google Drive / Colab Notebooks, 27 fevrier 2026, identifiant `1z27LcYeQjxjOP6NYX4r-uYzi_SbQDbBb`.
- `Copie de ds_lppls_pipeline.ipynb` : copie dans Drive, meme code des cellules, meta-donnees differentes ; non republiee pour eviter un doublon.
- Le code numerique de `legacy_engine.py` reprend les cellules 4, 6, 8, 10, 12, 14, 16, 18 et 20 de l'original : enveloppe de fonction ajoutee et garde explicite si aucune serie eligible.

## Historiquement produits : etat apres recuperation du ZIP du 4 novembre 2026

- `ds_lppls_pipeline_executed.ipynb` : **RECUPERE** depuis `lppls_notebooks_3_versions.zip` ; selon son README, **reconstruction NON EXECUTEE**, sans outputs ; ne pas confondre avec une execution d'origine.
- `ds_lppls_pipeline_with_backtest.ipynb` : **RECUPERE** ; appendice de presentation mais pas de moteur de backtest executable.
- `ds_lppls_pipeline_with_backtest_named.ipynb` : **RECUPERE** ; annexe de code de backtest reel, mais pas d'execution validee ; `skiprows=3` pour noms des actions.
- `lppls_backtest_named_notebook_and_outputs.zip` et `lppls_backtest_named_assets.zip`.
- `Rapport_backtest_LPPLS_SBF120.docx`.
- CSV historiques de NAV, positions, turnover, scenarios Long-only.

Les 3 fichiers ci-dessus proviennent de l'archive fournie au projet le 4 novembre 2026. Ils sont conserves SANS modification des cellules sous `notebooks/`, avec `README_ARCHIVE.txt` et les empreintes SHA256 dans `docs/BACKTEST_AUDIT.md`. Les autres archives/CSV sont encore non recuperes.

Le moteur `src/lppls_bubble/backtest.py` est une **adaptation corrigee**, pas un fichier historique : exclusion du look-ahead d'eligibilite et rebalancement effectif des poids. Les valeurs produites ne doivent donc pas etre presentees comme une reproduction identique des backtests passes.

## Limitations et risques

- La recherche sur grille de m, omega et tc est un estimateur rapide, non un protocole LPPLS certifie.
- Les criteres m et omega se trouvent a l'interieur des grilles de recherche et sont donc peu discriminants.
- Le seuil R2 >= 0.2 ne remplace pas une validation statistique ni une calibration de confiance.
- Les pondérations du notebook sont des snapshots ; **ce ne sont pas les backtests historiques**.
- Les biais d'anticipation, la gestion des valeurs manquantes, les frais, la selection univers et l'instabilite des parametres restent a auditer.
- Entrée : format de CSV historique SBF120 ; futur support d'un CSV standard explicite a realiser separement.

## Regle CI

Aucun fichier `.github/workflows` avant recette locale complete. Integrer plus tard un seul workflow manuel, sans `push` ou `pull_request` triggers, afin de minimiser l'usage Actions.
