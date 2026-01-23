from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import models, user_models, database
from api import transactions, accounts, categories, auth, bulk_upload
from core.config import settings
from core.exceptions import global_exception_handler

# Database Initialization
# In a larger system, migrations (Alembic) should handle this
models.Base.metadata.create_all(bind=database.engine)
user_models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    redirect_slashes=False
)

# Exception Handling
app.add_exception_handler(Exception, global_exception_handler)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# API Routes
app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(accounts.router)
app.include_router(categories.router)
app.include_router(bulk_upload.router)

@app.get("/")
def read_root():
    return {"message": f"Welcome to {settings.PROJECT_NAME}"}
