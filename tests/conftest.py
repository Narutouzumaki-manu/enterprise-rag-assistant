import os

# Must run before app.api.limits is imported: the limiter reads its settings at import time.
os.environ["RATE_LIMIT_STORAGE_URL"] = "memory://"