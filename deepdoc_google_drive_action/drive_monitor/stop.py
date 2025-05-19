"""Test Script used to stop a channel."""

import json

import requests

url = "https://f3tvj55t-5000.use.devtunnels.ms/api/stop"

payload = json.dumps({"channel_id": "60aed5c0-0f97-4307-87f2-ac18b47f41f0"})
headers = {"Content-Type": "application/json"}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)
