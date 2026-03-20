#!/usr/bin/env python3
"""Build the embedding index from data/results/ for prompt classification.

Usage:
    python3 scripts/build_embeddings.py

This reads all prompts from data/results/*.json, embeds them via Vertex AI
text-embedding-005, and saves the index to app/embeddings_index.json.
"""

import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    from app.embeddings import build_index, save_index

    logger.info("Building embedding index...")
    index = build_index()

    if not index:
        logger.error("No entries to index! Check data/results/ for valid prompts.")
        sys.exit(1)

    # Summary
    type_counts = {}
    for entry in index:
        tt = entry["task_type"]
        type_counts[tt] = type_counts.get(tt, 0) + 1

    logger.info(f"\nIndex summary: {len(index)} prompts, {len(type_counts)} task types")
    for tt, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        logger.info(f"  {tt}: {count}")

    save_index(index)
    logger.info("Done!")


if __name__ == "__main__":
    main()
