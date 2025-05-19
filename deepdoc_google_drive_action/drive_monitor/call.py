"""Test Watch resource API call to the dev tunnel."""

import json

import requests

url = "https://f3tvj55t-5000.use.devtunnels.ms/api/watch"

payload = json.dumps(
    {"resource_type": "folder", "resource_id": "1B3J83l7uMsmlho_tabJ_QSQnO1HTLwWd"}
)
headers = {"Content-Type": "application/json"}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)
