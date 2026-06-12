import ast
import glob
import sys

def check_file(filepath):
    with open(filepath, "r") as f:
        source = f.read()
    
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return
        
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            has_args = bool(node.args.args)
            if node.name == "__init__":
                has_args = len(node.args.args) > 1 # more than self
                
            has_return = False
            if node.returns and not (isinstance(node.returns, ast.Constant) and node.returns.value is None):
                if not (isinstance(node.returns, ast.Name) and node.returns.id == 'None'):
                    has_return = True
                    
            if not doc:
                print(f"{filepath}:{node.lineno} - {node.name} missing docstring entirely")
                continue
                
            if has_args and "Args:" not in doc:
                print(f"{filepath}:{node.lineno} - {node.name} missing 'Args:' in docstring")
            if has_return and "Returns:" not in doc and "Yields:" not in doc:
                print(f"{filepath}:{node.lineno} - {node.name} missing 'Returns:' in docstring")

for f in glob.glob("crawler/*.py"):
    check_file(f)
