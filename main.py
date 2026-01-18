from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from . import models, user_models, database
from .api import transactions, accounts, categories, auth

models.Base.metadata.create_all(bind=database.engine)
user_models.Base.metadata.create_all(bind=database.engine)


app = FastAPI(title="Prism API")

# Allow CORS for Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:3000",
    ],
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
