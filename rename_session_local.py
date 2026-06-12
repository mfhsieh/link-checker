import os

def replace_in_file(path, replacements):
    with open(path, 'r') as f:
        content = f.read()
    
    for old, new in replacements:
        content = content.replace(old, new)
        
    with open(path, 'w') as f:
        f.write(content)

# crawler/manager.py
manager_replacements = [
    ("import time\nfrom concurrent.futures", "import time\nfrom collections.abc import Callable\nfrom concurrent.futures"),
    ("SessionLocal (sessionmaker):", "session_factory (Callable[[], Session]):"),
    ("        # pylint: disable=invalid-name, unsubscriptable-object\n        self.SessionLocal: sessionmaker[Session] = sessionmaker(bind=self.engine)", "        self.session_factory: Callable[[], Session] = sessionmaker(bind=self.engine)"),
    ("self.SessionLocal", "self.session_factory")
]
replace_in_file("crawler/manager.py", manager_replacements)

# cli.py
cli_replacements = [
    ("manager.SessionLocal", "manager.session_factory")
]
replace_in_file("cli.py", cli_replacements)

# backend/deps.py
deps_replacements = [
    ("manager.SessionLocal", "manager.session_factory")
]
replace_in_file("backend/deps.py", deps_replacements)

print("Replacement complete.")
