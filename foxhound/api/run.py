"""Uvicorn entry point for the Foxhound API server."""

import uvicorn

from foxhound.api.app import app


def main() -> None:
    """Start the API server."""
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
