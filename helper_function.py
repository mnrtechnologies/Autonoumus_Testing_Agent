def extract_target_urls(data: dict) -> list[str]:
    """
    Return only valid target_url values from link features.
    """

    urls = []

    for step in data.get("steps", []):

        feature = step.get("feature", {})

        if feature.get("type") != "link":
            continue

        target_url = feature.get("target_url")

        if target_url:
            urls.append(target_url)

    return urls

import json

with open("output/session_20260216_115620/plans/main_action_plan_v8.json", "r", encoding="utf-8") as f:
    data = json.load(f)

links = extract_target_urls(data)

for link in links:
    print(link)
