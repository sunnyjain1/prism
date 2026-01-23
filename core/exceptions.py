from fastapi import Request, status
from fastapi.responses import JSONResponse
from core.config import settings
import traceback

async def global_exception_handler(request: Request, exc: Exception):
    error_msg = str(exc)
    print(f"Global Exception caught: {error_msg}")
    traceback.print_exc()
    
    content = {
        "detail": "Internal Server Error",
        "error_type": type(exc).__name__,
        "error_message": error_msg 
    }
    
    response = JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
        content=content
    )
    
    # Manual CORS injection for error responses
    origin = request.headers.get("origin")
    if origin and any(origin.startswith(o) for o in settings.ALLOWED_ORIGINS):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        
    return response
