import os
import logging
import httpx
from circuitbreaker import circuit, CircuitBreakerError
from app.http_client import get_http_client

logger = logging.getLogger(__name__)


@circuit(failure_threshold=3, recovery_timeout=30)
async def _fetch_geo_data(ip_address: str, api_key: str) -> dict:
    """
    Internal fetch — wrapped with circuit breaker.
    Opens after 3 consecutive failures, recovers after 30 seconds.
    """
    url = f"https://api.geoapify.com/v1/ipinfo?ip={ip_address}&apiKey={api_key}"
    client = get_http_client()
    response = await client.get(url, timeout=5.0)
    response.raise_for_status()
    data = response.json()
    return {
        "country": data.get("country", {}).get("name"),
        "state": data.get("state", {}).get("name"),
        "city": data.get("city", {}).get("name"),
    }


async def get_geo_data(ip_address: str) -> dict:
    """
    Fetches geographical data for a given IP address using the Geoapify API.
    Uses a circuit breaker to stop hammering a down service and avoid
    5-second timeouts on every chat request when Geoapify is unavailable.
    """
    geoapify_api_key = os.getenv("GEOAPIFY_API_KEY")
    if not geoapify_api_key:
        logger.warning("GEOAPIFY_API_KEY not set. Skipping Geoapify lookup.")
        return {}

    try:
        return await _fetch_geo_data(ip_address, geoapify_api_key)
    except CircuitBreakerError:
        logger.warning("Geoapify circuit breaker is open — skipping lookup for 30s")
        return {}
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

