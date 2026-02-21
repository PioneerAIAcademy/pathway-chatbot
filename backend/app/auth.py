import os

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _get_valid_api_keys() -> set:
    """Load valid API keys from environment variable."""
    keys = os.getenv("API_KEYS", "")
    return {k.strip() for k in keys.split(",") if k.strip()}


async def verify_api_key(api_key: str = Security(API_KEY_HEADER)) -> str:
    """
    Validate the API key from the X-API-Key request header.
    - In dev mode with no keys configured: allows all requests
    - In prod mode: strictly requires a valid key
    """
    environment = os.getenv("ENVIRONMENT", "dev")
    valid_keys = _get_valid_api_keys()

    # In dev mode with no keys configured, allow all requests
    if environment == "dev" and not valid_keys:
        return "dev"

    if not api_key or api_key not in valid_keys:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Provide a valid key in the X-API-Key header."
        )
    return api_key
