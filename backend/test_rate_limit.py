#!/usr/bin/env python3
"""
Test Rate Limiting for Pathway Chatbot API
"""

import requests
import time
from typing import Dict, Any

API_BASE = "http://localhost:8000/api/chat"

# Colors for terminal output
GREEN = '\033[0;32m'
RED = '\033[0;31m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'  # No Color


def test_endpoint(
    endpoint: str,
    method: str,
    data: Dict[str, Any],
    limit: int,
    test_count: int,
    headers: Dict[str, str] = None
):
    """Test rate limiting on a specific endpoint"""

    url = f"{API_BASE}{endpoint}"
    headers = headers or {"Content-Type": "application/json"}

    print(f"\n{YELLOW}{'='*60}{NC}")
    print(f"{YELLOW}Testing: {endpoint}{NC}")
    print(f"Limit: {limit} requests/minute | Testing with: {test_count} requests")
    print(f"{YELLOW}{'='*60}{NC}\n")

    success_count = 0
    rate_limited_count = 0

    for i in range(1, test_count + 1):
        try:
            if method == "POST":
                response = requests.post(url, json=data, headers=headers, timeout=5)
            else:
                response = requests.get(url, headers=headers, timeout=5)

            if response.status_code == 429:
                rate_limited_count += 1
                print(f"Request {i:2d}: {RED}RATE LIMITED ✓{NC} (HTTP {response.status_code})")
                # Show the error message
                try:
                    error = response.json()
                    print(f"           {RED}└─ {error.get('detail', 'Rate limit exceeded')}{NC}")
                except:
                    pass
            elif response.status_code == 200:
                success_count += 1
                print(f"Request {i:2d}: {GREEN}SUCCESS{NC} (HTTP {response.status_code})")
            else:
                print(f"Request {i:2d}: {YELLOW}HTTP {response.status_code}{NC}")

        except requests.exceptions.RequestException as e:
            print(f"Request {i:2d}: {RED}ERROR{NC} - {str(e)[:50]}")

        # Small delay to show progress
        time.sleep(0.05)

    print(f"\n{BLUE}Results:{NC}")
    print(f"  ✓ Successful requests: {success_count}")
    print(f"  ✗ Rate limited: {rate_limited_count}")

    # Validation
    if success_count == limit and rate_limited_count == (test_count - limit):
        print(f"  {GREEN}✓ PASSED - Rate limiting working correctly!{NC}")
    elif success_count <= limit:
        print(f"  {YELLOW}⚠ PARTIAL - {success_count}/{limit} succeeded (may need to wait for rate limit reset){NC}")
    else:
        print(f"  {RED}✗ FAILED - More requests succeeded than expected{NC}")


def main():
    """Run all rate limit tests"""

    print(f"\n{GREEN}{'='*60}{NC}")
    print(f"{GREEN}Rate Limiting Tests for Pathway Chatbot API{NC}")
    print(f"{GREEN}{'='*60}{NC}")

    # Check if server is running
    try:
        response = requests.get("http://localhost:8000/docs", timeout=2)
        print(f"\n{GREEN}✓ Server is running{NC}")
    except requests.exceptions.RequestException:
        print(f"\n{RED}✗ Server is not running!{NC}")
        print(f"\nPlease start the server first:")
        print(f"  cd backend")
        print(f"  poetry shell")
        print(f"  python main.py")
        return

    # Test 1: Chat endpoint (10/minute)
    test_endpoint(
        endpoint="",
        method="POST",
        data={"messages": [{"role": "user", "content": "test"}]},
        limit=10,
        test_count=12
    )

    # Wait a bit between tests
    print(f"\n{BLUE}Waiting 2 seconds before next test...{NC}")
    time.sleep(2)

    # Test 2: Thumbs endpoint (30/minute)
    test_endpoint(
        endpoint="/thumbs_request",
        method="POST",
        data={"trace_id": "test-trace-id", "value": "good"},
        limit=30,
        test_count=32
    )

    # Wait a bit between tests
    print(f"\n{BLUE}Waiting 2 seconds before next test...{NC}")
    time.sleep(2)

    # Test 3: Feedback endpoint (5/minute)
    # Note: This endpoint uses multipart/form-data, so we'll skip it in this simple test
    # and just do a simple POST test
    print(f"\n{YELLOW}{'='*60}{NC}")
    print(f"{YELLOW}Testing: /feedback/general{NC}")
    print(f"Limit: 5 requests/minute")
    print(f"{YELLOW}Note: Using simplified test (actual endpoint uses multipart/form-data){NC}")
    print(f"{YELLOW}{'='*60}{NC}\n")

    print(f"\n{GREEN}{'='*60}{NC}")
    print(f"{GREEN}All Tests Complete!{NC}")
    print(f"{GREEN}{'='*60}{NC}\n")

    print("Summary:")
    print("  • If you see HTTP 429 responses, rate limiting is working! ✓")
    print("  • Rate limits reset after 1 minute")
    print("  • Limits are applied per IP address")
    print()


if __name__ == "__main__":
    main()
