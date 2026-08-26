import hashlib
import hmac
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

try:
    from database import Base, SessionLocal, engine, get_db
    from engine import LedgerEvent, RatePoint, calculate_ledger
    from models import Account, AccountRateHistory, Transaction, User
    from schemas import AccountCreate, AccountResponse, RateHistoryCreate, RateHistoryResponse, SessionRequest, SummaryResponse, TokenResponse, TransactionCreate, TransactionResponse
except ModuleNotFoundError:  # pragma: no cover - supports package-loading from the repo root
    from backend.database import Base, SessionLocal, engine, get_db
    from backend.engine import LedgerEvent, RatePoint, calculate_ledger
    from backend.models import Account, AccountRateHistory, Transaction, User
    from backend.schemas import AccountCreate, AccountResponse, RateHistoryCreate, RateHistoryResponse, SessionRequest, SummaryResponse, TokenResponse, TransactionCreate, TransactionResponse

JWT_SECRET = os.getenv("JWT_SECRET", "development-only-secret")
JWT_ALGORITHM = "HS256"
TOKEN_TTL = timedelta(hours=12)
origins = [item.strip() for item in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if item.strip()]

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
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session owner not found")
    return user


def owned_account(account_id: UUID, user: User, db: Session) -> Account:
    account = db.scalar(select(Account).where(Account.id == account_id, Account.user_id == user.id))
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@app.on_event("startup")
def create_tables() -> None:
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
        user = User(username=request.username, pin_hash=hash_pin(request.pin))
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not verify_pin(request.pin, user.pin_hash):
        raise HTTPException(status_code=401, detail="Username or PIN is invalid")
    payload = {"sub": str(user.id), "exp": datetime.now(timezone.utc) + TOKEN_TTL}
    return TokenResponse(access_token=jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM), username=user.username)


@app.get("/accounts", response_model=list[AccountResponse])
def list_accounts(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[Account]:
    return list(db.scalars(select(Account).where(Account.user_id == user.id).order_by(Account.label)))


@app.post("/accounts", response_model=AccountResponse, status_code=201)
def create_account(
    request: AccountCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Account:
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



@app.get("/accounts/{account_id}/rates", response_model=list[RateHistoryResponse])
def list_rates(account_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[AccountRateHistory]:
    owned_account(account_id, user, db)
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
    owned_account(account_id, user, db)
    return list(db.scalars(select(Transaction).where(Transaction.account_id == account_id).order_by(Transaction.effective_date, Transaction.id)))


@app.post("/accounts/{account_id}/transactions", response_model=TransactionResponse, status_code=201)
def create_transaction(account_id: UUID, request: TransactionCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Transaction:
    owned_account(account_id, user, db)
    transaction = Transaction(account_id=account_id, **request.model_dump())
    db.add(transaction)
    db.commit()
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
    account = owned_account(account_id, user, db)
    events = [LedgerEvent(item.effective_date, item.type, item.amount) for item in account.transactions]
    rates = [RatePoint(item.effective_date, item.interest_rate, item.penal_rate) for item in account.rate_history]
    result = calculate_ledger(events, account.sanctioned_limit, rates)
    result["net_cost"] = result["total_interest_accrued"] + result["total_penalties_charged"] + result["incidental_charges"]
    result["total_outstanding"] = result["principal"] + result["accrued_interest"] + result["penalty_balance"]
    return result
