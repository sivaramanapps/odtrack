import hashlib
import hmac
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

try:
    from database import Base, SessionLocal, engine, get_db
    from engine import LedgerEvent, RatePoint, calculate_ledger
    from models import Account, AccountMember, AccountRateHistory, AppSetting, Transaction, User
    from schemas import AccountCreate, AccountResponse, AdminPasswordReset, AdminSettings, AdminUserResponse, PasswordChange, RateHistoryCreate, RateHistoryResponse, SessionRequest, SummaryResponse, TokenResponse, TransactionCreate, TransactionResponse, UserPolicyUpdate, ViewerAccountsUpdate, ViewerCreate, ViewerPassword, ViewerResponse
except ModuleNotFoundError:  # pragma: no cover - supports package-loading from the repo root
    from backend.database import Base, SessionLocal, engine, get_db
    from backend.engine import LedgerEvent, RatePoint, calculate_ledger
    from backend.models import Account, AccountMember, AccountRateHistory, AppSetting, Transaction, User
    from backend.schemas import AccountCreate, AccountResponse, AdminPasswordReset, AdminSettings, AdminUserResponse, PasswordChange, RateHistoryCreate, RateHistoryResponse, SessionRequest, SummaryResponse, TokenResponse, TransactionCreate, TransactionResponse, UserPolicyUpdate, ViewerAccountsUpdate, ViewerCreate, ViewerPassword, ViewerResponse

JWT_SECRET = os.getenv("JWT_SECRET", "development-only-secret")
JWT_ALGORITHM = "HS256"
TOKEN_TTL = timedelta(hours=12)
origins = [item.strip() for item in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if item.strip()]
admin_username = os.getenv("ADMIN_USERNAME")
admin_pin = os.getenv("ADMIN_PIN")
registration_enabled = os.getenv("REGISTRATION_ENABLED", "true").lower() == "true"

app = FastAPI(title="ODTrack Ledger API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
bearer = HTTPBearer(auto_error=False)


def hash_pin(pin: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 210_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split("$", 1)
    expected = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt_hex), 210_000).hex()
    return hmac.compare_digest(expected, digest_hex)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer session required")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = UUID(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    user = db.get(User, user_id)
    if not user or not user.is_approved:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session owner not found")
    return user


def owned_account(account_id: UUID, user: User, db: Session) -> Account:
    account = db.scalar(select(Account).where(Account.id == account_id, Account.user_id == user.id))
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def accessible_account(account_id: UUID, user: User, db: Session) -> Account:
    account = db.scalar(
        select(Account).join(AccountMember, isouter=True).where(
            Account.id == account_id,
            (Account.user_id == user.id) | (AccountMember.user_id == user.id),
        )
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator permission required")
    return user


@app.on_event("startup")
def create_tables() -> None:
    if os.getenv("CREATE_TABLES_ON_STARTUP", "false").lower() == "true":
        # This is a convenience for local development and testing. In production, the database schema should be managed via migrations.
        Base.metadata.create_all(bind=engine)
    # Serverless startup must not run schema bootstrap against Supabase.
    # Tables are provisioned manually before deployment, and create_all() can
    # block the cold start path during Vercel invocation.
    pass


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/debug/db")
def debug_db(db: Session = Depends(get_db)) -> dict:
    from sqlalchemy import text

    result = db.execute(
        text("""
            SELECT
                current_database() AS database,
                current_schema() AS schema,
                (
                    SELECT character_maximum_length
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'transactions'
                      AND column_name = 'type'
                ) AS transaction_type_length
        """)
    ).mappings().one()

    return dict(result)



@app.post("/auth/session", response_model=TokenResponse)
def create_session(request: SessionRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.username == request.username))
    if not user:
        configured_registration = db.get(AppSetting, "registration_enabled")
        registration_allowed = configured_registration.value == "true" if configured_registration else registration_enabled
        if admin_username and request.username == admin_username:
            if not admin_pin or request.pin != admin_pin:
                raise HTTPException(status_code=401, detail="Administrator password is invalid")
            user = User(username=request.username, pin_hash=hash_pin(request.pin), is_admin=True, is_approved=True)
        elif not registration_allowed:
            raise HTTPException(status_code=403, detail="New user registration is currently disabled")
        else:
            user = User(username=request.username, pin_hash=hash_pin(request.pin), is_approved=False)
            db.add(user)
            db.commit()
            raise HTTPException(status_code=202, detail="User created and is awaiting administrator approval")
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not user.is_approved:
        raise HTTPException(status_code=403, detail="User creation is awaiting administrator approval")
    elif not verify_pin(request.pin, user.pin_hash):
        raise HTTPException(status_code=401, detail="Username or PIN is invalid")
    payload = {"sub": str(user.id), "exp": datetime.now(timezone.utc) + TOKEN_TTL}
    return TokenResponse(access_token=jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM), username=user.username, view_only=user.is_view_only, is_admin=user.is_admin)


@app.post("/auth/password", status_code=204)
def change_password(request: PasswordChange, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    if not verify_pin(request.current_pin, user.pin_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.pin_hash = hash_pin(request.new_pin)
    db.commit()


@app.delete("/auth/user", status_code=204)
def delete_user(user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    db.delete(user)
    db.commit()


@app.get("/accounts", response_model=list[AccountResponse])
def list_accounts(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[Account]:
    accounts = list(db.scalars(select(Account).join(AccountMember, isouter=True).where((Account.user_id == user.id) | (AccountMember.user_id == user.id)).order_by(Account.label)))
    return [AccountResponse.model_validate(account).model_copy(update={"view_only": account.user_id != user.id}) for account in accounts]


@app.post("/accounts", response_model=AccountResponse, status_code=201)
def create_account(
    request: AccountCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Account:
    if user.is_view_only:
        raise HTTPException(status_code=403, detail="View-only users cannot create accounts")
    if user.account_limit is not None and db.scalar(select(func.count(Account.id)).where(Account.user_id == user.id)) >= user.account_limit:
        raise HTTPException(status_code=403, detail="Your account limit has been reached")
    account = Account(user_id=user.id, **request.model_dump())
    db.add(account)
    db.flush()

    db.add(
        AccountRateHistory(
            account_id=account.id,
            effective_date=account.created_at.date(),
            interest_rate=account.interest_rate * 100,
            penal_rate=account.penal_rate * 100,
        )
    )

    db.commit()
    db.refresh(account)
    return account


@app.get("/admin/settings", response_model=AdminSettings)
def get_admin_settings(user: User = Depends(admin_user), db: Session = Depends(get_db)) -> AdminSettings:
    setting = db.get(AppSetting, "registration_enabled")
    return AdminSettings(registration_enabled=setting.value == "true" if setting else registration_enabled)


@app.patch("/admin/settings", response_model=AdminSettings)
def update_admin_settings(request: AdminSettings, user: User = Depends(admin_user), db: Session = Depends(get_db)) -> AdminSettings:
    setting = db.get(AppSetting, "registration_enabled")
    if setting:
        setting.value = str(request.registration_enabled).lower()
    else:
        db.add(AppSetting(key="registration_enabled", value=str(request.registration_enabled).lower()))
    db.commit()
    return request


@app.get("/admin/users", response_model=list[AdminUserResponse])
def list_admin_users(user: User = Depends(admin_user), db: Session = Depends(get_db)) -> list[AdminUserResponse]:
    users = db.scalars(select(User).order_by(User.username)).all()
    return [AdminUserResponse(id=item.id, username=item.username, is_admin=item.is_admin, is_approved=item.is_approved, is_view_only=item.is_view_only, account_limit=item.account_limit, account_count=db.scalar(select(func.count(Account.id)).where(Account.user_id == item.id)) or 0) for item in users]


@app.patch("/admin/users/{user_id}", response_model=AdminUserResponse)
def update_admin_user(user_id: UUID, request: UserPolicyUpdate, user: User = Depends(admin_user), db: Session = Depends(get_db)) -> AdminUserResponse:
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == user.id and request.is_approved is False:
        raise HTTPException(status_code=400, detail="You cannot suspend the current administrator")
    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(target, field, value)
    db.commit()
    return AdminUserResponse(id=target.id, username=target.username, is_admin=target.is_admin, is_approved=target.is_approved, is_view_only=target.is_view_only, account_limit=target.account_limit, account_count=db.scalar(select(func.count(Account.id)).where(Account.user_id == target.id)) or 0)


@app.post("/admin/users/{user_id}/password", status_code=204)
def reset_user_password(user_id: UUID, request: AdminPasswordReset, user: User = Depends(admin_user), db: Session = Depends(get_db)) -> None:
    target = db.get(User, user_id)
    if not target or target.id == user.id:
        raise HTTPException(status_code=400, detail="Use your own password change option for the current administrator")
    target.pin_hash = hash_pin(request.new_pin)
    db.commit()


@app.delete("/admin/users/{user_id}", status_code=204)
def delete_admin_user(user_id: UUID, user: User = Depends(admin_user), db: Session = Depends(get_db)) -> None:
    target = db.get(User, user_id)
    if not target or target.id == user.id:
        raise HTTPException(status_code=400, detail="Cannot delete this user")
    db.delete(target)
    db.commit()


@app.delete("/accounts/{account_id}", status_code=204)
def delete_account(account_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    account = owned_account(account_id, user, db)
    db.delete(account)
    db.commit()


@app.post("/accounts/{account_id}/viewers", response_model=ViewerResponse, status_code=201)
def create_viewer(account_id: UUID, request: ViewerCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> ViewerResponse:
    account = owned_account(account_id, user, db)
    if db.scalar(select(User).where(User.username == request.username)):
        raise HTTPException(status_code=409, detail="Username already exists")
    viewer = User(username=request.username, pin_hash=hash_pin(request.pin), is_view_only=True, created_by_user_id=user.id)
    db.add(viewer)
    db.flush()
    db.add(AccountMember(account_id=account.id, user_id=viewer.id, role="viewer"))
    db.commit()
    return ViewerResponse(username=viewer.username, account_id=account.id)


@app.post("/viewers", response_model=ViewerResponse, status_code=201)
def create_global_viewer(request: ViewerCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> ViewerResponse:
    if user.is_view_only:
        raise HTTPException(status_code=403, detail="View-only users cannot create users")
    if db.scalar(select(User).where(User.username == request.username)):
        raise HTTPException(status_code=409, detail="Username already exists")
    viewer = User(username=request.username, pin_hash=hash_pin(request.pin), is_view_only=True, created_by_user_id=user.id)
    db.add(viewer)
    db.commit()
    return ViewerResponse(username=viewer.username)


@app.get("/accounts/{account_id}/viewers", response_model=list[ViewerResponse])
def list_viewers(account_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[ViewerResponse]:
    account = owned_account(account_id, user, db)
    members = db.scalars(select(AccountMember).where(AccountMember.account_id == account.id)).all()
    return [ViewerResponse(username=member.user.username, account_id=account.id) for member in members]


@app.get("/viewers/{username}/accounts", response_model=list[AccountResponse])
def list_viewer_accounts(username: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[AccountResponse]:
    viewer = db.scalar(select(User).where(User.username == username, User.is_view_only.is_(True)))
    if not viewer:
        raise HTTPException(status_code=404, detail="View-only user not found")
    owned = db.scalars(select(Account).where(Account.user_id == user.id)).all()
    if viewer.created_by_user_id != user.id and not db.scalar(select(AccountMember).join(Account, Account.id == AccountMember.account_id).where(AccountMember.user_id == viewer.id, Account.user_id == user.id)):
        raise HTTPException(status_code=403, detail="You do not manage this view-only user")
    mapped = db.scalars(select(AccountMember.account_id).where(AccountMember.user_id == viewer.id)).all()
    return [AccountResponse.model_validate(account) for account in owned if account.id in mapped]


@app.put("/viewers/{username}/accounts", response_model=list[AccountResponse])
def update_viewer_accounts(username: str, request: ViewerAccountsUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[AccountResponse]:
    viewer = db.scalar(select(User).where(User.username == username, User.is_view_only.is_(True)))
    if not viewer:
        raise HTTPException(status_code=404, detail="View-only user not found")
    owned = db.scalars(select(Account).where(Account.user_id == user.id)).all()
    if viewer.created_by_user_id != user.id and not db.scalar(select(AccountMember).join(Account, Account.id == AccountMember.account_id).where(AccountMember.user_id == viewer.id, Account.user_id == user.id)):
        raise HTTPException(status_code=403, detail="You do not manage this view-only user")
    owned_ids = {account.id for account in owned}
    if not set(request.account_ids).issubset(owned_ids):
        raise HTTPException(status_code=403, detail="You can map only your own accounts")
    db.query(AccountMember).filter(AccountMember.user_id == viewer.id).delete(synchronize_session=False)
    db.add_all([AccountMember(account_id=account_id, user_id=viewer.id, role="viewer") for account_id in request.account_ids])
    db.commit()
    return [AccountResponse.model_validate(account) for account in owned if account.id in set(request.account_ids)]


@app.delete("/accounts/{account_id}/viewers/{username}", status_code=204)
def delete_viewer(account_id: UUID, username: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    account = owned_account(account_id, user, db)
    viewer = db.scalar(select(User).where(User.username == username, User.is_view_only.is_(True)))
    member = viewer and db.scalar(select(AccountMember).where(AccountMember.account_id == account.id, AccountMember.user_id == viewer.id))
    if not member:
        raise HTTPException(status_code=404, detail="View-only user not found")
    db.delete(member)
    db.commit()


@app.post("/accounts/{account_id}/viewers/{username}/password", status_code=204)
def change_viewer_password(account_id: UUID, username: str, request: ViewerPassword, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    account = owned_account(account_id, user, db)
    viewer = db.scalar(select(User).where(User.username == username, User.is_view_only.is_(True)))
    member = viewer and db.scalar(select(AccountMember).where(AccountMember.account_id == account.id, AccountMember.user_id == viewer.id))
    if not member:
        raise HTTPException(status_code=404, detail="View-only user not found")
    viewer.pin_hash = hash_pin(request.pin)
    db.commit()


@app.post("/viewers/{username}/password", status_code=204)
def change_global_viewer_password(username: str, request: ViewerPassword, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    viewer = db.scalar(select(User).where(User.username == username, User.is_view_only.is_(True)))
    if not viewer or (viewer.created_by_user_id != user.id and not db.scalar(select(AccountMember).join(Account, Account.id == AccountMember.account_id).where(AccountMember.user_id == viewer.id, Account.user_id == user.id))):
        raise HTTPException(status_code=404, detail="View-only user not found")
    viewer.pin_hash = hash_pin(request.pin)
    db.commit()



@app.get("/accounts/{account_id}/rates", response_model=list[RateHistoryResponse])
def list_rates(account_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[AccountRateHistory]:
    accessible_account(account_id, user, db)
    return list(db.scalars(select(AccountRateHistory).where(AccountRateHistory.account_id == account_id).order_by(AccountRateHistory.effective_date)))


@app.post("/accounts/{account_id}/rates", response_model=RateHistoryResponse, status_code=201)
def create_rate(account_id: UUID, request: RateHistoryCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> AccountRateHistory:
    account = owned_account(account_id, user, db)
    rate = AccountRateHistory(account_id=account.id, **request.model_dump())
    db.add(rate)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="A rate already exists for that effective date")
    db.refresh(rate)
    return rate


@app.get("/accounts/{account_id}/transactions", response_model=list[TransactionResponse])
def list_transactions(account_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[Transaction]:
    accessible_account(account_id, user, db)
    return list(db.scalars(select(Transaction).where(Transaction.account_id == account_id).order_by(Transaction.effective_date, Transaction.id)))


@app.post("/accounts/{account_id}/transactions", response_model=TransactionResponse, status_code=201)
def create_transaction(account_id: UUID, request: TransactionCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Transaction:
    owned_account(account_id, user, db)
    transaction = Transaction(account_id=account_id, **request.model_dump())
    db.add(transaction)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if "ck_transaction_type" in str(error.orig):
            raise HTTPException(status_code=400, detail="This transaction type is not enabled in the database. Apply the latest migrations.")
        raise HTTPException(status_code=400, detail="Transaction could not be saved")
    db.refresh(transaction)
    return transaction


@app.delete("/accounts/{account_id}/transactions/{transaction_id}", status_code=204)
def delete_transaction(account_id: UUID, transaction_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    owned_account(account_id, user, db)
    transaction = db.scalar(select(Transaction).where(Transaction.id == transaction_id, Transaction.account_id == account_id))
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    db.delete(transaction)
    db.commit()


@app.get("/accounts/{account_id}/summary", response_model=SummaryResponse)
def account_summary(account_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    account = accessible_account(account_id, user, db)
    events = [LedgerEvent(item.effective_date, item.type, item.amount) for item in account.transactions]
    rates = [RatePoint(item.effective_date, item.interest_rate, item.penal_rate) for item in account.rate_history]
    result = calculate_ledger(events, account.sanctioned_limit, rates)
    result["net_cost"] = result["total_interest_accrued"] + result["total_penalties_charged"] + result["incidental_charges"]
    #result["net_cost"] += result["bank_charges"]
    result["total_outstanding"] = max(
        result["principal"] + result["accrued_interest"] + result["penalty_balance"] + result["bank_charge_balance"] - result["credit_balance"],
        Decimal("0"),
    )
    return result
