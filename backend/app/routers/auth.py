from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Hospital, Insurer, PatientProfile, User
from app.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.security import create_access_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(access_token=create_access_token(user), user=UserOut.model_validate(user))


def _authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")
    return user


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")
    if body.role in ("hospital", "insurer") and not body.organization_name:
        raise HTTPException(422, f"Enter the {body.role}'s name.")

    user = User(email=email, password_hash=hash_password(body.password), full_name=body.full_name, role=body.role)
    db.add(user)
    db.flush()
    if body.role == "patient":
        db.add(PatientProfile(user_id=user.id))
    elif body.role == "hospital":
        db.add(Hospital(user_id=user.id, name=body.organization_name, city=body.city or "",
                        city_tier=body.city_tier, hospital_type=body.hospital_type))
    else:
        db.add(Insurer(user_id=user.id, name=body.organization_name))
    db.commit()
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    return _token_response(_authenticate(db, body.email, body.password))


@router.post("/token", response_model=TokenResponse, include_in_schema=True,
             summary="OAuth2 form login (used by the Swagger 'Authorize' button)")
def token(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    return _token_response(_authenticate(db, form.username, form.password))


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    data = UserOut.model_validate(user).model_dump()
    if user.hospital:
        data["hospital"] = {"id": user.hospital.id, "name": user.hospital.name, "city": user.hospital.city,
                            "city_tier": user.hospital.city_tier, "hospital_type": user.hospital.hospital_type}
    if user.insurer:
        data["insurer"] = {"id": user.insurer.id, "name": user.insurer.name}
    return data
