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

# Stage 1: Query understanding messages
QUERY_MESSAGES = [
    "Understanding your question...",
    "Interpreting request...",
    "Analyzing query...",
]

# Stage 3: Synthesis/generation messages
SYNTHESIZE_MESSAGES = [
    "Synthesizing response...",
    "Drafting answer...",
    "Composing response...",
]

# Stage 3.5: LLM generation start messages
LLM_MESSAGES = [
    "Generating response...",
    "Producing answer...",
    "Formulating reply...",
]

# Stage 4: Reranking messages
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


def get_query_message() -> str:
    """Returns a random query understanding message."""
    return random.choice(QUERY_MESSAGES)


def get_synthesize_message() -> str:
    """Returns a random synthesis message."""
    return random.choice(SYNTHESIZE_MESSAGES)


def get_llm_message() -> str:
    """Returns a random LLM generation message."""
    return random.choice(LLM_MESSAGES)


def get_reranking_message() -> str:
    """Returns a random reranking message (for future use)."""
    return random.choice(RERANKING_MESSAGES)
