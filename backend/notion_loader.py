import os
import requests
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

class NotionPageLoader:
    """Minimal loader for fetching Notion pages and blocks."""

    def __init__(self, token: str, notion_version: str = "2022-06-28"):
        """
        Args:
            token (str): Notion API integration token.
            notion_version (str): Notion API version. Defaults to '2022-06-28'.
        """
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": notion_version,
        }

    def search_all_pages(self) -> List[str]:
        """
        Search all pages in Notion.

        Returns:
            List of page IDs.
        """
        url = "https://api.notion.com/v1/search"
        payload = {
            "filter": {"value": "page", "property": "object"},
            "sort": {"direction": "descending", "timestamp": "last_edited_time"}
        }
        page_ids = []
        next_cursor = None
        try:
            while True:
                request_payload = dict(payload)
                if next_cursor:
                    request_payload["start_cursor"] = next_cursor
                response = requests.post(
                    url,
                    headers=self.headers,
                    json=request_payload,
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()
                page_ids.extend(
                    result["id"]
                    for result in data.get("results", [])
                    if result.get("object") == "page"
                )
                if not data.get("has_more"):
                    return page_ids
                next_cursor = data.get("next_cursor")
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to search pages: {e}") from e

    def get_page_title(self, page_id: str) -> str:
        """
        Get the title of a Notion page.

        Args:
            page_id (str): Notion page ID.

        Returns:
            Page title or 'Untitled' if not found.
        """
        url = f"https://api.notion.com/v1/pages/{page_id}"
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            props = data.get("properties", {})
            for prop in props.values():
                if prop.get("type") == "title":
                    title_data = prop.get("title", [])
                    if title_data:
                        return "".join([t["plain_text"] for t in title_data])
            return "Untitled"
        except requests.RequestException as e:
            print(f"Failed to get title for page {page_id}: {e}")
            return "Untitled"

    def get_block_children(self, block_id: str) -> List[Dict[str, Any]]:
        """
        Fetch all child blocks of a Notion page or block.

        Args:
            block_id (str): Block or page ID.

        Returns:
            List of block data.
        """
        url = f"https://api.notion.com/v1/blocks/{block_id}/children"
        results = []
        next_cursor = None
        while True:
            try:
                params = {"start_cursor": next_cursor} if next_cursor else {}
                response = requests.get(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()
                results.extend(data.get("results", []))
                if not data.get("has_more"):
                    return results
                next_cursor = data.get("next_cursor")
            except requests.RequestException as e:
                raise RuntimeError(
                    f"Failed to fetch blocks for {block_id}: {e}"
                ) from e

    def get_block_content(self, block: Dict[str, Any]) -> str:
        """
        Extract text content from a Notion block.

        Args:
            block: Block data from Notion API.

        Returns:
            Block text as string.
        """
        block_type = block.get("type", "unknown")
        block_data = block.get(block_type, {})
        try:
            if "rich_text" in block_data:
                return "".join([t.get("plain_text", "") for t in block_data["rich_text"]])
            elif block_type == "code":
                return "[Code]\n" + "".join([t.get("plain_text", "") for t in block_data.get("rich_text", [])])
            elif block_type == "image":
                return "[Image]"
            else:
                return f"[{block_type} block]"
        except Exception:
            return f"[{block_type} block]"

    def get_page_blocks(self, page_id: str) -> List[Dict[str, str]]:
        """
        Fetch and extract text blocks for a page.

        Args:
            page_id (str): Notion page ID.

        Returns:
            List of block data (text, timestamp).
        """
        blocks = self.get_block_children(page_id)
        result = []
        for block in blocks:
            text = self.get_block_content(block)
            result.append({"text": text, "timestamp": block.get("last_edited_time")})
        return result
