import requests
from django.conf import settings


class PaySuiteError(Exception):
    pass


def _headers():
    if not settings.PAYSUITE_API_TOKEN:
        raise PaySuiteError("PAYSUITE_API_TOKEN não configurado.")
    return {
        "Authorization": f"Bearer {settings.PAYSUITE_API_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def create_payment_request(
    *,
    amount: str,
    reference: str,
    description: str,
    return_url: str,
    callback_url: str,
    method: str | None = None,
):
    """
    POST /api/v1/payments
    Retorna: {id, checkout_url, ...}
    """
    url = f"{settings.PAYSUITE_API_BASE}/payments"
    payload = {
        "amount": str(amount),
        "reference": reference,
        "description": description,
        "return_url": return_url,
        "callback_url": callback_url,
    }
    if method:
        payload["method"] = method

    r = requests.post(url, headers=_headers(), json=payload, timeout=25)
    data = r.json() if r.content else {}

    if r.status_code not in (200, 201) or data.get("status") != "success":
        raise PaySuiteError(data.get("message") or f"PaySuite error ({r.status_code})")
    return data["data"]


def get_payment(paysuite_uuid: str):
    """
    GET /api/v1/payments/{uuid}
    Retorna um dict em data, ex:
    {"id": "...", "reference": "...", "transaction": {"status":"completed", ...}}
    """
    url = f"{settings.PAYSUITE_API_BASE}/payments/{paysuite_uuid}"
    r = requests.get(url, headers=_headers(), timeout=20)
    data = r.json() if r.content else {}

    if r.status_code != 200 or data.get("status") != "success":
        raise PaySuiteError(data.get("message") or f"PaySuite error ({r.status_code})")
    return data["data"]