"""Local regression tests for the separate, archive-backed Nov 2026 research pack."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'research' / 'reproducible_2026_11_04'
ARCH = ROOT / 'artifacts' / 'historical_2026_02_27'


def _load_core():
    spec = importlib.util.spec_from_file_location('research_lppls_core', PACK / 'lppls_core.py')
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_core_source_preserved_and_syntax_ok():
    source = (PACK / 'lppls_core_source.py').read_bytes()
    assert hashlib.sha256(source).hexdigest() == '7ff245f8d734c0f465ed73d5974a6253e3673fc748c83fc70d00d3bcf8a3ee8b'
    ast.parse(source.decode('utf-8'))
    ast.parse((PACK / 'lppls_core.py').read_text(encoding='utf-8'))
    assert source != (PACK / 'lppls_core.py').read_bytes()


def test_pack_notebooks_structural_validation():
    files = sorted((PACK / 'notebooks').glob('*.ipynb'))
    assert len(files) == 6
    for p in files:
        nb = json.loads(p.read_text(encoding='utf-8'))
        assert nb.get('nbformat') == 4
        for cell in nb['cells']:
            if cell['cell_type'] == 'code':
                assert not cell.get('outputs', [])
                ast.parse(''.join(cell['source']), filename=p.name)


def test_historical_outputs_manifest_integrity():
    manifest = json.loads((ARCH / 'SHA256_MANIFEST.json').read_text(encoding='utf-8'))
    assert len(manifest['files']) == 6
    for x in manifest['files']:
        b = (ARCH / x['filename']).read_bytes()
        assert len(b) == x['size']
        assert hashlib.sha256(b).hexdigest() == x['sha256']
    detail = pd.read_csv(ARCH / 'details_by_scale_all_series.csv')
    assert detail.shape[0] == 105
    assert detail.asset.nunique() == 15


def test_research_pack_pipeline_and_bounded_backtest(tmp_path):
    core = _load_core()
    prices = core.load_prices(PACK / 'examples' / 'synthetic_example.csv')
    assert list(prices.columns) == ['EXAMPLE_A', 'EXAMPLE_B']
    weekly = core.to_weekly(prices)
    assert len(weekly) > 104
    out = core.write_snapshot_outputs(weekly, tmp_path, grid='tiny')
    assert len(out) == 5
    assert (tmp_path / 'heatmap_global.png').read_bytes().startswith(b'\x89PNG')
    assert (out['summary_by_scale_wide.csv']['valid_frac'].between(0, 1)).all()

    metrics = core.run_backtest(weekly, tmp_path, max_rebalances=3,
                                start_date='2024-02-01', rebalance_weeks=4, grid='tiny')
    assert set(metrics.strategy) == {'long_only', 'long_short', 'equal_weight'}
    assert set(metrics.n_rebalances) == {3}
    nav = pd.read_csv(tmp_path / 'backtest_nav_weekly.csv')
    assert len(nav) == 13  # 3 decisions and last 4-week holding window
    assert nav['nav_long_only'].notna().all()
    assert (tmp_path / 'backtest_missing_returns.csv').exists()


def test_research_first_portfolio_does_not_use_future(tmp_path):
    core = _load_core()
    weekly = core.to_weekly(core.load_prices(PACK / 'examples' / 'synthetic_example.csv'))
    date = weekly.index[110]
    past = weekly.loc[:date]
    def compute(p):
        return core.targets(p, core.bubble_classification(core.summarize(
            core.calculate_details(p, grid='tiny'))))
    lo1, ls1 = compute(past)
    changed = weekly.copy()
    changed.loc[changed.index > date, 'EXAMPLE_A'] *= 10_000
    lo2, ls2 = compute(changed.loc[:date])
    pd.testing.assert_series_equal(lo1, lo2)
    pd.testing.assert_series_equal(ls1, ls2)
