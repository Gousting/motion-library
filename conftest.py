"""pytest 根配置：把项目根加入 sys.path，保证 `from scripts import ...` 可用。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
