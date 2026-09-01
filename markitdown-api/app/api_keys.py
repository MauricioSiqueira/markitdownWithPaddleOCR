"""
Chaves de API válidas armazenadas como hashes SHA-512.

Para gerar uma nova chave e seu hash:
    python3 -c "
    import hashlib, secrets
    raw = secrets.token_urlsafe(32)
    hashed = hashlib.sha512(raw.encode()).hexdigest()
    print('RAW KEY:', raw)
    print('SHA-512:', hashed)
    "

Adicione apenas o hash (SHA-512) nesta lista — nunca a chave em texto puro.
O cliente deve enviar a chave raw via query param ?api_key=<raw>.
"""

API_KEYS: list[str] = [
    # Chave de exemplo — substitua pelo hash gerado para sua chave real
    "cc5da9058d58f23b0af4673c607c63b945a17f4ff3db907a73ade6f3350a14794d9fe0562a47732f651347b320210f2e7dbb36393e9392de082230a6700d6604",
]
