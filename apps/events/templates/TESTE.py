import requests

event_id = 'EVNT17772834386503'

url = f"https://eticketsmz.site/borrow/external/events/{event_id}"

headers = {
    "Authorization": "Bearer etk_live_3SZPEA7FNCZAdqjIaBIIbI7j"
}

resp = requests.get(url, headers=headers, timeout=10)

print(f"Status: {resp.status_code}")

try:
    data = resp.json()
    print(data)
except ValueError:
    print("Resposta não é JSON:")
    print(resp.text[:500])  # evita print gigante