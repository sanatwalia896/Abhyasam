import os
import json
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()

class NotionPageLoader:
    """Handles fetching and caching Notion pages for Abhyasam collections."""
    
    def __init__(self, token: str, parent_page_id: Optional[str] = None, cache_file: str = "cached_pages.json", notion_version: str = "2022-06-28"):
        """
        Initialize NotionPageLoader for fetching pages under a parent page.

        Args:
            token (str): Notion API integration token.
            parent_page_id (Optional[str]): ID of parent page containing collection. If None, searches all pages.
            cache_file (str): Path to cache file. Defaults to 'cached_pages.json'.
            notion_version (str): Notion API version. Defaults to '2022-06-28'.
        """
        self.token = token
        self.parent_page_id = parent_page_id
        self.cache_file = cache_file
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": notion_version,
        }

    def get_all_page_contents(self) -> List[Dict[str, Any]]:
        """
        Load cached Notion pages if available.

        Returns:
            List of page data (id, title, content, last_edited_time) or empty list.
        """
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r") as f:
                    return json.load(f)
            return []
        except Exception as e:
            logger.error(f"Failed to read cache: {e}")
            return []

    def refresh_and_cache_pages(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Fetch and cache Notion pages, updating only new or changed pages unless forced.

        Args:
            force_refresh (bool): If True, refresh all pages regardless of changes.

        Returns:
            List of page data (id, title, content, last_edited_time).
        """
        logger.info("Syncing Notion pages...")
        cached_pages = {page["id"]: page for page in self.get_all_page_contents()}
        page_ids = self.search_all_pages()
        all_data = []

        for page_id in page_ids:
            try:
                cached_page = cached_pages.get(page_id)
                last_edited = self._get_page_last_edited(page_id)
                
                # Skip if unchanged and not forcing refresh
                if not force_refresh and cached_page and cached_page.get("last_edited_time") == last_edited:
                    all_data.append(cached_page)
                    continue
                
                title = self.get_page_title(page_id)
                content_blocks = self.get_page_blocks(page_id)
                content = "\n".join([b["text"] for b in content_blocks])
                page_data = {
                    "id": page_id,
                    "title": title,
                    "content": content,
                    "last_edited_time": last_edited
                }
                all_data.append(page_data)
                logger.info(f"Updated page: {title} ({page_id})")
            except Exception as e:
                logger.error(f"Error processing page {page_id}: {e}")
                continue

        try:
            with open(self.cache_file, "w") as f:
                json.dump(all_data, f, indent=2)
            logger.info(f"Cached {len(all_data)} Notion pages to {self.cache_file}")
        except Exception as e:
            logger.error(f"Failed to write cache: {e}")
        
        return all_data

    def search_all_pages(self) -> List[str]:
        """
        Search all pages in Notion, optionally under a parent page.

        Returns:
            List of page IDs.
        """
        url = "https://api.notion.com/v1/search"
        payload = {
            "filter": {"value": "page", "property": "object"},
            "sort": {"direction": "descending", "timestamp": "last_edited_time"}
        }
        if self.parent_page_id:
            payload["filter"]["parent"] = {"page_id": self.parent_page_id}
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return [result["id"] for result in data.get("results", []) if result["object"] == "page"]
        except requests.RequestException as e:
            logger.error(f"Failed to search pages: {e}")
            return []

    def _get_page_last_edited(self, page_id: str) -> Optional[str]:
        """
        Get the last edited timestamp of a page.

        Args:
            page_id (str): Notion page ID.

        Returns:
            ISO timestamp string or None if error.
        """
        url = f"https://api.notion.com/v1/pages/{page_id}"
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json().get("last_edited_time")
        except requests.RequestException as e:
            logger.error(f"Failed to get last edited time for page {page_id}: {e}")
            return None

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
            response = requests.get(url, headers=self.headers)
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
            logger.error(f"Failed to get title for page {page_id}: {e}")
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
        while url:
            try:
                response = requests.get(url, headers=self.headers)
                response.raise_for_status()
                data = response.json()
                results.extend(data.get("results", []))
                url = f"{url}?start_cursor={data['next_cursor']}" if data.get("has_more") else None
            except requests.RequestException as e:
                logger.error(f"Failed to fetch blocks for {block_id}: {e}")
                return results
        return results

    def get_block_content(self, block: Dict[str, Any]) -> str:
        """
        Extract content from a Notion block.

        Args:
            block: Block data from Notion API.

        Returns:
            Formatted block content as string.
        """
        block_type = block.get("type", "unknown")
        block_data = block.get(block_type, {})
        try:
            if "rich_text" in block_data:
                return "".join([t.get("plain_text", "") for t in block_data["rich_text"]])
            elif block_type == "code":
                return f"[Code]\n" + "".join([t.get("plain_text", "") for t in block_data.get("rich_text", [])])
            elif block_type == "image":
                return "[Image]"
            else:
                return f"[{block_type} block]"
        except Exception as e:
            logger.error(f"Error processing block {block_type}: {e}")
            return f"[{block_type} block]"

    def get_page_blocks(self, page_id: str, filter_last_edited_days: int = 0) -> List[Dict[str, str]]:
        """
        Fetch and filter blocks for a page.

        Args:
            page_id (str): Notion page ID.
            filter_last_edited_days (int): Skip blocks older than this many days.

        Returns:
            List of block data (text, timestamp).
        """
        blocks = self.get_block_children(page_id)
        result = []
        cutoff = datetime.utcnow() - timedelta(days=filter_last_edited_days) if filter_last_edited_days > 0 else None
        for block in blocks:
            last_edited = block.get("last_edited_time")
            if last_edited and cutoff:
                edited_dt = datetime.fromisoformat(last_edited.replace("Z", "+00:00"))
                if edited_dt < cutoff:
                    continue
            try:
                text = self.get_block_content(block)
                result.append({"text": text, "timestamp": last_edited})
            except Exception as e:
                logger.error(f"Error processing block in page {page_id}: {e}")
        return result