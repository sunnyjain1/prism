from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from . import models, database
from .api import transactions, accounts, categories

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Prism API")

# Allow CORS for Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # adjust in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transactions.router)
app.include_router(accounts.router)
app.include_router(categories.router)

@app.get("/")
def read_root():
    return {"message": "Welcome to Prism API"}
