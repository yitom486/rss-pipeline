"""Compatibility import. Run this project through uv; implementation lives in src/."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from rss_pipeline.agent import *  # noqa: F403
