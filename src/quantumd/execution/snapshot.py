import shutil
import tempfile
from pathlib import Path

class ReadOnlySnapshot:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir.resolve()
        self.snapshot_dir = Path(tempfile.mkdtemp(prefix="quantumd_exec_"))
        
    def __enter__(self):
        shutil.copytree(
            self.project_dir, 
            self.snapshot_dir, 
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("evidence*", ".venv*", ".repairs*", "*.bak*", "__pycache__*")
        )
        return self.snapshot_dir
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        shutil.rmtree(self.snapshot_dir, ignore_errors=True)
