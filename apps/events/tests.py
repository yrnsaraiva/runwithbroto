from django.test import TestCase
import requests

url = "https://etk-api.up.railway.app/back/borrow/external/events"

headers = {
    "Authorization": "Bearer etk_live_2btldp22PSu8AmsSyhdeDE-s"
}


r = requests.get(url, headers=headers, timeout=10)

print(f"Status: {r.status_code}")

try:
    data = r.json()
    print(data)
except ValueError:
    print("Resposta não é JSON:")
    print(r.text[:500])  # evita print gigante

