"""Test list channels API call to the dev tunnel."""

import json

import requests

url = "https://f3tvj55t-5000.use.devtunnels.ms/api/channels"

payload = json.dumps({})
headers = {"Content-Type": "application/json"}

response = requests.request("GET", url, headers=headers, data=payload)

print(response.text)
