# Inventaire de migration et journal des reserves

Date : 2026-11-04.

## Source verifiee

- `ds_lppls_pipeline.ipynb` : Google Drive / Colab Notebooks, 27 fevrier 2026, identifiant `1z27LcYeQjxjOP6NYX4r-uYzi_SbQDbBb`.
- `Copie de ds_lppls_pipeline.ipynb` : copie dans Drive, meme code des cellules, meta-donnees differentes ; non republiee pour eviter un doublon.
- Le code numerique de `legacy_engine.py` reprend les cellules 4, 6, 8, 10, 12, 14, 16, 18 et 20 de l'original : enveloppe de fonction ajoutee et garde explicite si aucune serie eligible.

## Historiquement produits, fichier source non recupere

- `ds_lppls_pipeline_executed.ipynb` ; `lppls_livrables.zip`.
- `ds_lppls_pipeline_with_backtest.ipynb`.
- `ds_lppls_pipeline_with_backtest_named.ipynb` (correction du header `skiprows=3`).
- `lppls_backtest_named_notebook_and_outputs.zip` et `lppls_backtest_named_assets.zip`.
- `Rapport_backtest_LPPLS_SBF120.docx`.
- CSV historiques de NAV, positions, turnover, scenarios Long-only.

Ces developpements ont ete decrits/livres dans des chats du 27 fevrier 2026 mais ne sont pas disponibles dans le dossier Drive Colab Notebooks audite. Ne pas les reconstituer en les presentant comme code original.

## Limitations et risques

- La recherche sur grille de m, omega et tc est un estimateur rapide, non un protocole LPPLS certifie.
- Les criteres m et omega se trouvent a l'interieur des grilles de recherche et sont donc peu discriminants.
- Le seuil R2 >= 0.2 ne remplace pas une validation statistique ni une calibration de confiance.
- Les pondérations du notebook sont des snapshots ; **ce ne sont pas les backtests historiques**.
- Les biais d'anticipation, la gestion des valeurs manquantes, les frais, la selection univers et l'instabilite des parametres restent a auditer.
- Entrée : format de CSV historique SBF120 ; futur support d'un CSV standard explicite a realiser separement.

## Regle CI

Aucun fichier `.github/workflows` avant recette locale complete. Integrer plus tard un seul workflow manuel, sans `push` ou `pull_request` triggers, afin de minimiser l'usage Actions.
