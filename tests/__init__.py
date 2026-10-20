import os
import tempfile

os.environ["NYX_HOME"] = tempfile.mkdtemp(prefix="nyx-test-home-")
