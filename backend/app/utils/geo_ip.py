import os
import logging
import httpx
from app.http_client import get_http_client

logger = logging.getLogger(__name__)

async def get_geo_data(ip_address: str) -> dict:
    """
    Fetches geographical data for a given IP address using the Geoapify API.
    Uses shared HTTP client to prevent connection leaks
    """
    geoapify_api_key = os.getenv("GEOAPIFY_API_KEY")
    if not geoapify_api_key:
        logger.warning("GEOAPIFY_API_KEY not set. Skipping Geoapify lookup.")
        return {}

    url = f"https://api.geoapify.com/v1/ipinfo?ip={ip_address}&apiKey={geoapify_api_key}"

    try:
        # Use shared client instead of creating new one per request
        client = get_http_client()
        response = await client.get(url, timeout=5.0)
        response.raise_for_status()  # Raise an exception for HTTP errors (4xx or 5xx)
        data = response.json()

        country = data.get("country", {}).get("name")
        state = data.get("state", {}).get("name")
        city = data.get("city", {}).get("name")

        return {
            "country": country,
            "state": state,
            "city": city,
        }
    except httpx.RequestError as exc:
        logger.error(f"An error occurred while requesting Geoapify: {exc}")
        return {}
    except httpx.HTTPStatusError as exc:
        logger.error(
            f"Geoapify API returned an error - {exc.response.status_code}: {exc.response.text}"
        )
        return {}
    except Exception as exc:
        logger.error(f"An unexpected error occurred during Geoapify lookup: {exc}")
        return {}

