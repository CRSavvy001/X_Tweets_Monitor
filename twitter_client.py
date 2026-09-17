"""Minimal async client for twitterapi.io.

Docs: https://docs.twitterapi.io/api-reference/endpoint/get_user_last_tweets
"""

import httpx

BASE_URL = "https://api.twitterapi.io"


class TwitterAPIError(Exception):
    pass


class TwitterAPIClient:
    def __init__(self, api_key: str, timeout: float = 15.0):
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"X-API-Key": api_key},
            timeout=timeout,
        )

    async def get_last_tweets(self, username: str) -> list[dict]:
        """Return the user's tweets, newest first (as the API returns them)."""
        resp = await self._client.get(
            "/twitter/user/last_tweets", params={"userName": username}
        )
        if resp.status_code != 200:
            raise TwitterAPIError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()

        # twitterapi.io returns {"status": "error", "message": "..."} on failure
        if isinstance(data, dict) and data.get("status") == "error":
            raise TwitterAPIError(data.get("message", "unknown error"))

        tweets = None
        if isinstance(data, dict):
            tweets = data.get("tweets")
            if tweets is None and isinstance(data.get("data"), dict):
                tweets = data["data"].get("tweets")
        return tweets or []

    async def aclose(self):
        await self._client.aclose()
