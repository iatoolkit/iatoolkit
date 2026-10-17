"""Load the deployment under the same module name used inside the image."""

import importlib.util
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'distribution', root / '__init__.py', submodule_search_locations=[str(root)]
)
module = importlib.util.module_from_spec(spec)
sys.modules['distribution'] = module
spec.loader.exec_module(module)
