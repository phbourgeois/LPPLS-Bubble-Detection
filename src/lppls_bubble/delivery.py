"""Build a single, self-describing archive for Streamlit LPPLS deliverables."""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from io import BytesIO
import json
from pathlib import PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


README = """# Livrables LPPLS — archive de l'exécution Streamlit

Cette archive contient les fichiers réellement produits pendant une même exécution.

- donnees/source.csv : fichier de prix original fourni à l'application ;
- donnees/quality_events.csv : registre fourni pour les blocages, le cas échéant ;
- audit/ : anomalies, décisions réutilisables et données effectivement analysées ;
- lppls/ : estimations, classifications, pondérations instantanées, heatmap,
  rapport HTML et rapport PDF ;
- backtest/ : NAV hebdomadaires, performances, poids, états LPPLS,
  turnover, diagnostics de qualité et graphique NAV, si le backtest a réussi ;
- statistique/ : diagnostic statistique expérimental, s'il a été demandé
  et calculé ;
- manifest.json : paramètres, statut des calculs, taille et SHA-256 de chaque fichier.

L'absence d'une section s'explique par le statut enregistré dans le manifest.
Le backtest reste exploratoire : les coûts, les événements sur titres et la
qualité des données nécessitent une vérification indépendante.
"""


def _check_file(name: str, value: bytes) -> None:
    # Only plain filenames are accepted from the exporters; no traversal.
    if (not isinstance(name, str) or not name or
            PurePosixPath(name).name != name or
            "/" in name or "\\" in name or name in (".", "..")):
        raise ValueError(f"Nom de livrable non sécurisé : {name!r}")
    if not isinstance(value, bytes):
        raise TypeError(f"Le livrable {name!r} doit être un objet bytes")


def build_delivery_zip(
    snapshot_exports: Mapping[str, bytes],
    backtest_exports: Mapping[str, bytes] | None = None,
    statistical_exports: Mapping[str, bytes] | None = None,
    *,
    audit_exports: Mapping[str, bytes] | None = None,
    source_csv: bytes | None = None,
    source_name: str | None = None,
    event_register_csv: bytes | None = None,
    parameters: Mapping[str, object] | None = None,
    run_status: Mapping[str, str] | None = None,
) -> bytes:
    """Build an in-memory ZIP of one completed Streamlit run.

    No recalculation, file substitution or loss of the original output names.
    The manifest gives the recipient the exact parameters and file hashes.
    """
    if not snapshot_exports:
        raise ValueError("L'archive doit contenir au moins un livrable LPPLS")
    if source_csv is not None and not isinstance(source_csv, bytes):
        raise TypeError("source_csv doit être bytes")
    if event_register_csv is not None and not isinstance(event_register_csv, bytes):
        raise TypeError("event_register_csv doit être bytes")

    files: dict[str, bytes] = {}
    for folder, mapping in (
        ("lppls", snapshot_exports),
        ("backtest", backtest_exports or {}),
        ("statistique", statistical_exports or {}),
        ("audit", audit_exports or {}),
    ):
        for name, data in mapping.items():
            _check_file(name, data)
            files[f"{folder}/{name}"] = data
    if source_csv is not None:
        files["donnees/source.csv"] = source_csv
    if event_register_csv is not None:
        files["donnees/quality_events.csv"] = event_register_csv

    # Insertion-order-independent manifest and ZIP, facilitating comparisons.
    entries = [
        {"path": path, "size_bytes": len(files[path]),
         "sha256": sha256(files[path]).hexdigest()}
        for path in sorted(files)
    ]
    manifest = {
        "format_version": 1,
        "source_filename": source_name,
        "parameters": dict(parameters or {}),
        "run_status": dict(run_status or {}),
        "file_count": len(entries),
        "files": entries,
    }
    files["README.md"] = README.encode("utf-8")
    files["manifest.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n"
    ).encode("utf-8")

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(files):
            entry = ZipInfo(path, date_time=(2020, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, files[path], compress_type=ZIP_DEFLATED, compresslevel=6)
    return buffer.getvalue()
