from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from app.tripletex import TripletexClient

logger = logging.getLogger(__name__)

# Type alias for handler functions
HandlerFunc = Callable[[TripletexClient, dict[str, Any]], Awaitable[dict[str, Any]]]

# Registry: task_type string → handler function
HANDLER_REGISTRY: dict[str, HandlerFunc] = {}


def register_handler(task_type: str):
    """Decorator to register a handler for a task type."""
    def decorator(func: HandlerFunc) -> HandlerFunc:
        HANDLER_REGISTRY[task_type] = func
        logger.info(f"Registered handler: {task_type}")
        return func
    return decorator


async def execute_task(task_type: str, client: TripletexClient, fields: dict[str, Any], prompt: str = "") -> dict[str, Any]:
    """Look up and run the handler for task_type. Returns result dict."""
    # Handle batch tasks: batch_create_department → run create_department for each item
    if task_type.startswith("batch_"):
        base_type = task_type[6:]  # Remove "batch_" prefix
        items = fields.get("items", [])
        logger.info(f"Batch dispatch: {task_type} — {len(items)} items, base_type={base_type}")
        results = []
        for item in items:
            # Each item may have its own taskType — use it if available
            if isinstance(item, dict):
                item_type = item.get("taskType", base_type)
                item_fields = item.get("fields", item)
            else:
                item_type = base_type
                item_fields = {}

            item_handler = HANDLER_REGISTRY.get(item_type)
            if item_handler is None:
                # Fallback to base_type handler
                item_handler = HANDLER_REGISTRY.get(base_type)
            if item_handler is None:
                logger.warning(f"No handler for batch item type: {item_type}")
                results.append({"status": "completed", "note": f"No handler for: {item_type}"})
                continue

            item_idx = len(results) + 1
            logger.info(f"Batch item {item_idx}/{len(items)}: taskType={item_type}")

            # Pass prompt to fallback/unknown handlers that need it
            if item_type == "unknown" or item_handler == HANDLER_REGISTRY.get("unknown"):
                result = await item_handler(client, item_fields, prompt=prompt)
            else:
                result = await item_handler(client, item_fields)

            # Log batch item result for debugging
            created = result.get("created", {})
            if not created or (isinstance(created, dict) and not created.get("id")):
                logger.warning(
                    f"Batch item {item_idx}/{len(items)} ({item_type}): "
                    f"empty created — {result.get('error', 'unknown')}"
                )
            else:
                created_id = created.get("id") if isinstance(created, dict) else "list"
                logger.info(f"Batch item {item_idx}/{len(items)} ({item_type}): created id={created_id}")
            results.append(result)
        return {"status": "completed", "taskType": task_type, "batch_results": results}

    handler = HANDLER_REGISTRY.get(task_type)
    if handler is None:
        # Use fallback handler for unregistered task types
        fallback = HANDLER_REGISTRY.get("unknown")
        if fallback and prompt:
            logger.info(f"No handler for task type {task_type}, using fallback")
            return await fallback(client, fields, prompt=prompt)
        logger.warning(f"No handler for task type: {task_type}")
        return {"status": "completed", "note": f"No handler for task type: {task_type}"}

    # For the "unknown" task type, pass the prompt
    if task_type == "unknown":
        return await handler(client, fields, prompt=prompt)

    return await handler(client, fields)


# Import handler modules so they self-register
from app.handlers import tier1  # noqa: E402,F401
from app.handlers import tier2_invoice  # noqa: E402,F401
from app.handlers import tier2_travel  # noqa: E402,F401
from app.handlers import tier2_project  # noqa: E402,F401
from app.handlers import tier3  # noqa: E402,F401
from app.handlers import tier2_extra  # noqa: E402,F401
from app.handlers import fallback  # noqa: E402,F401
