import ast
import sys

def summarize(filepath):
    with open(filepath, "r") as f:
        source = f.read()
    tree = ast.parse(source)
    print(f"--- {filepath} ---")
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            print(f"Class: {node.name} (line {node.lineno} to {node.end_lineno})")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            print(f"Function: {node.name} (line {node.lineno} to {node.end_lineno})")

summarize("backend/jobs/router.py")
summarize("backend/jobs/service.py")
