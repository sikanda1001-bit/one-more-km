import os
import sys

# Ensure project root is on path so `import app` works on Vercel
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import app  # noqa: F401 — Vercel looks for `app`
