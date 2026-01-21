from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import models, user_models, database
from api import transactions, accounts, categories, auth
import os

models.Base.metadata.create_all(bind=database.engine)
user_models.Base.metadata.create_all(bind=database.engine)


app = FastAPI(title="Prism API")

# Load CORS origins from environment (comma-separated) or use defaults
default_origins = "http://localhost:5174,http://127.0.0.1:5174,http://localhost:3000"
allowed_origins = os.environ.get("ALLOWED_ORIGINS", default_origins).split(",")

# Allow CORS for Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(accounts.router)
app.include_router(categories.router)

@app.get("/")
def read_root():
    return {"message": "Welcome to Prism API"}
