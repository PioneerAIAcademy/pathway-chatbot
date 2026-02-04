"""
Message variations for RAG pipeline status indicators.
Provides randomized status messages to avoid repetitive user experience.
"""

import random

# Stage 2: Retrieval start messages
RETRIEVAL_MESSAGES = [
    "Looking for content...",
    "Searching knowledge base...",
    "Finding relevant sources...",
    "Retrieving information...",
]

# Stage 4: Reranking messages (not currently used, but ready for future)
RERANKING_MESSAGES = [
    "Ranking sources by relevance...",
    "Analyzing source quality...",
    "Selecting best matches...",
    "Prioritizing results...",
    "Evaluating sources...",
]


def get_retrieval_start_message() -> str:
    """Returns a random retrieval start message."""
    return random.choice(RETRIEVAL_MESSAGES)


def get_reranking_message() -> str:
    """Returns a random reranking message (for future use)."""
    return random.choice(RERANKING_MESSAGES)
