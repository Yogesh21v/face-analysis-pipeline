"""
Both Lambda functions are named app.py in their own directories (matching
how they'd actually be deployed), so a plain `import app` in different test
files would collide -- whichever module loads first wins the `sys.modules`
cache and gets reused (silently wrong) for the other. This loads each one
under its own unique module name via importlib instead.
"""
import importlib.util
import sys


def load_lambda_module(file_path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
