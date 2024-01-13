import os

DTHUB_SCHEMA: str = "https"
DTHUB_HOST: str = os.environ.get("DTHUB_HOST", "hub.duckietown.com")
DTHUB_API_VERSION: str = "v1"
DTHUB_API_URL: str = f"{DTHUB_SCHEMA}://{DTHUB_HOST}/api/{DTHUB_API_VERSION}"
