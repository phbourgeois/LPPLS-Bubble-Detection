from .legacy_engine import DEFAULT_WINDOWS, run_snapshot
from .backtest import BacktestSettings, load_weekly, run_backtest

REFERENCE_ENGINE = "src/lppls_bubble"
VALIDATION_STATUS = "EXPLORATORY_NOT_STATISTICALLY_VALIDATED"

__all__ = ["DEFAULT_WINDOWS", "run_snapshot", "BacktestSettings", "load_weekly", "run_backtest", "REFERENCE_ENGINE", "VALIDATION_STATUS"]
