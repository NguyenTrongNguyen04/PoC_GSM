$ErrorActionPreference = "Stop"
python scripts\validate_contracts.py
python scripts\validate_knowledge.py --scope offline-fixture --strict
python -m unittest discover -s tests -v
