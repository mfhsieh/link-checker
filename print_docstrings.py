import ast
def print_docstrings(filepath):
    with open(filepath, "r") as f:
        source = f.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("__"):
            doc = ast.get_docstring(node)
            print(f"[{node.name}] Line: {node.lineno}")
            print(f"{doc}\n")
print_docstrings("crawler/core.py")
