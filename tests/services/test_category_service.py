import pytest
from fastapi import HTTPException
from services.category_service import CategoryService
from schemas import CategoryCreate
from models import Category, TransactionType
from user_models import User

@pytest.fixture
def category_service(db_session):
    return CategoryService(db_session)

@pytest.fixture
def setup_user(db_session):
    user = User(id="user1", email="test@example.com", hashed_password="hashed")
    db_session.add(user)
    db_session.commit()
    return user

def test_create_category(category_service, setup_user):
    user = setup_user
    cat_in = CategoryCreate(id="cat1", name="Food", type=TransactionType.expense, color="#ff0000")
    cat = category_service.create_category(cat_in, user.id)
    assert cat.name == "Food"
    assert cat.owner_id == user.id

def test_get_categories(category_service, setup_user):
    user = setup_user
    category_service.create_category(CategoryCreate(id="cat1", name="C1", type=TransactionType.expense), user.id)
    categories = category_service.get_categories(user.id)
    assert len(categories) == 1

def test_delete_category(category_service, setup_user):
    user = setup_user
    cat = category_service.create_category(CategoryCreate(id="cat1", name="C1", type=TransactionType.expense), user.id)
    category_service.delete_category(cat.id, user.id)
    
    categories = category_service.get_categories(user.id)
    assert len(categories) == 0

def test_delete_category_not_found(category_service, setup_user):
    user = setup_user
    with pytest.raises(HTTPException) as exc:
        category_service.delete_category("non-existent", user.id)
    assert exc.value.status_code == 404

def test_create_default_categories(category_service, setup_user):
    user = setup_user
    category_service.create_default_categories(user.id)
    
    categories = category_service.get_categories(user.id)
    # Check if we have at least one income and one expense category
    income_cats = [c for c in categories if c.type == "income"]
    expense_cats = [c for c in categories if c.type == "expense"]
    
    assert len(categories) == 11 # Total 11 categories in defaults
    assert len(income_cats) == 3
    assert len(expense_cats) == 8
