from django.test import TestCase
import requests

url = "https://eticketsmz.site/borrow/external/tickets"

payload = {
    "priceId": "PRC17727248575767",
    "eventId": "EVNT17727200000001",
    "phone": "258845343113"
}

headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer etk_live_3SZPEA7FNCZAdqjIaBIIbI7j"
}

r = requests.post(url, json=payload, headers=headers)

print(r.status_code)
print(r.json())
