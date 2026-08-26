import os
import requests

URL = "https://gyqoaningqhurhvdugne.supabase.co/functions/v1/payment-orchestrator"

API_KEY = "sk_live_smMQHwfPCYQnHSBgJ0bt4dYbICG5yV53"


payload = {
    "action": "process",
    "payment_method": "mpesa",
    # "merchant_id": "e5d6a8d9-e5f6-476e-b2b8-13cc3ef19788",
    "amount": 500,
    "currency": "MZN",
    "phone": "258849651834",
}

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}


response = requests.post(
    URL,
    headers=headers,
    json=payload,
    timeout=30,
)

print("=" * 60)
print(f"HTTP Status: {response.status_code}")
print("=" * 60)

print("Headers:")
for key, value in response.headers.items():
    print(f"{key}: {value}")

print("\nResposta:")


print(response.json())


