from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

bearer = HTTPBearer(auto_error=False)


async def require_token(cred: HTTPAuthorizationCredentials = Security(bearer)):
    if cred is None or cred.credentials != settings.api_token:
        raise HTTPException(401, "invalid token")
    return cred.credentials
