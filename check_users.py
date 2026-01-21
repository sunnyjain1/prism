from prism.database import SessionLocal
from prism.user_models import User
db = SessionLocal()
users = db.query(User).all()
for u in users:
    print(f"ID: {u.id}, Email: {u.email}, Name: {u.full_name}, Role: {u.role}")
db.close()
