"""Minimal async client for twitterapi.io.

Docs:
- https://docs.twitterapi.io/api-reference/endpoint/get_user_last_tweets
- https://docs.twitterapi.io/api-reference/endpoint/tweet_advanced_search
"""

import asyncio
import httpx

BASE_URL = "https://api.twitterapi.io"


class TwitterAPIError(Exception):
    pass


def _extract_tweets(data) -> list[dict]:
    """Handle both response shapes twitterapi.io endpoints use."""
    if not isinstance(data, dict):
        return []
    tweets = data.get("tweets")
    if tweets is None and isinstance(data.get("data"), dict):
        tweets = data["data"].get("tweets")
    return tweets or []


class TwitterAPIClient:
    def __init__(self, api_key: str, timeout: float = 15.0):
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"X-API-Key": api_key},
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=0, keepalive_expiry=0),
        )

    async def _get(self, path: str, params: dict, retries: int = 2) -> dict:
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                resp = await self._client.get(path, params=params)
            except httpx.HTTPError as e:
                last_err = e
                if attempt < retries:
                    await asyncio.sleep(1.5)
                    continue
                raise TwitterAPIError(f"network error after {retries} retries: {e!r}") from e

            if resp.status_code != 200:
                raise TwitterAPIError(f"HTTP {resp.status_code}: {resp.text[:200]}")

            data = resp.json()
            if isinstance(data, dict) and data.get("status") == "error":
                raise TwitterAPIError(data.get("message", "unknown error"))
            return data

        raise TwitterAPIError(f"network error: {last_err!r}")

    async def get_last_tweets_raw(self, username: str) -> tuple[int, str]:
        """Return (status_code, raw_response_text) with no parsing at all."""
        resp = await self._client.get(
            "/twitter/user/last_tweets", params={"userName": username}
        )
        return resp.status_code, resp.text

    async def get_last_tweets(self, username: str) -> list[dict]:
        data = await self._get("/twitter/user/last_tweets", {"userName": username})
        return _extract_tweets(data)

    async def search_user_tweets(self, username: str) -> list[dict]:
        """Fallback: search index instead of the timeline endpoint. Useful for
        accounts that user/last_tweets returns empty for even though they
        have visible tweets."""
        data = await self._get(
            "/twitter/tweet/advanced_search",
            {"query": f"from:{username}", "queryType": "Latest"},
        )
        return _extract_tweets(data)

    async def get_user_tweets_with_fallback(self, username: str) -> list[dict]:
        tweets = await self.get_last_tweets(username)
        if tweets:
            return tweets
        return await self.search_user_tweets(username)

    async def aclose(self):
        await self._client.aclose()
