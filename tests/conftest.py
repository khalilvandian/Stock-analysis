import importlib.util
import sys
from pathlib import Path

# Make analysis/absolute.py importable as `analysis_absolute` (analysis/ is not a package).
_path = Path(__file__).resolve().parent.parent / "analysis" / "absolute.py"
_spec = importlib.util.spec_from_file_location("analysis_absolute", _path)
_module = importlib.util.module_from_spec(_spec)
sys.modules["analysis_absolute"] = _module
_spec.loader.exec_module(_module)
