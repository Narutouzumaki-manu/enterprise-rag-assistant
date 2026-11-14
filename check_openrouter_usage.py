
import os

import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    raise SystemExit("OPENROUTER_API_KEY was not found in .env")

response = requests.get(
    "https://openrouter.ai/api/v1/key",
    headers={"Authorization": f"Bearer {api_key}"},
    timeout=15,
)

print("HTTP status:", response.status_code)
response.raise_for_status()
data = response.json().get("data", {})

print("\n--- OpenRouter API key usage ---")
for field in (
    "label",
    "is_free_tier",
    "usage",
    "limit",
    "limit_remaining",
    "usage_daily",
    "usage_weekly",
    "usage_monthly",
    "rate_limit",
    "free_model_daily_requests",
):
    if field in data:
        print(f"{field}: {data[field]}")

if "free_model_daily_requests" not in data:
    print(
        "\nDaily free-model request details were not returned "
        "for this key. This does not mean the quota is zero."
    )
