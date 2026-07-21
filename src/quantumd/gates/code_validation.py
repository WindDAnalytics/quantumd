import ast
from pathlib import Path

def validate_code(project_dir: Path, manifest: dict):
    entrypoint = manifest.get("implementation", {}).get("entrypoint")
    if not entrypoint:
        raise ValueError("Manifest missing 'implementation.entrypoint'")
    
    entrypoint_path = project_dir / entrypoint
    if not entrypoint_path.exists():
        raise FileNotFoundError(f"Declared entrypoint missing: {entrypoint}")
        
    source_code = entrypoint_path.read_text(encoding='utf-8')
    
    try:
        # Parse AST without executing to catch syntax errors safely
        tree = ast.parse(source_code, filename=entrypoint_path.name)
    except SyntaxError as e:
        error_line = e.text.strip() if e.text else ""
        raise ValueError(f"SyntaxError at line {e.lineno}: '{error_line}'")
        
    # Check for banned security imports (DevSecOps)
    banned = {'os', 'subprocess', 'sys'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split('.')[0] in banned:
                    raise PermissionError(f"Security violation: Banned import '{alias.name}' detected.")
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split('.')[0] in banned:
                raise PermissionError(f"Security violation: Banned import '{node.module}' detected.")
                
    return True
