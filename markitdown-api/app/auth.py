import hashlib

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyQuery

from app.api_keys import API_KEYS

_api_key_query = APIKeyQuery(name="api_key", auto_error=False)


def verify_api_key(api_key: str = Security(_api_key_query)) -> str:
    if not api_key:
        raise HTTPException(status_code=401, detail="API Key não informada.")

    hashed = hashlib.sha512(api_key.encode()).hexdigest()

    if hashed not in API_KEYS:
        raise HTTPException(status_code=403, detail="API Key inválida.")

    return api_key
