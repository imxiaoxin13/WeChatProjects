from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PointAccount, PointLedger


def get_locked_account(db: Session, user_id: str) -> PointAccount:
    account = db.scalar(select(PointAccount).where(PointAccount.user_id == user_id).with_for_update())
    if not account:
        account = PointAccount(user_id=user_id, balance=0, frozen=0)
        db.add(account)
        db.flush()
    return account


def _exists(db: Session, key: str) -> bool:
    return db.scalar(select(PointLedger.id).where(PointLedger.idempotency_key == key)) is not None


def _record(db: Session, account: PointAccount, *, kind: str, amount: int, reference_type: str,
            reference_id: str, key: str, note: str | None = None) -> None:
    db.add(PointLedger(
        user_id=account.user_id,
        kind=kind,
        amount=amount,
        balance_after=account.balance,
        frozen_after=account.frozen,
        reference_type=reference_type,
        reference_id=reference_id,
        idempotency_key=key,
        note=note,
    ))


def reserve(db: Session, user_id: str, points: int, reference_type: str, reference_id: str, key: str) -> bool:
    ledger_key = f"reserve:{key}"
    if _exists(db, ledger_key):
        return False
    account = get_locked_account(db, user_id)
    if points <= 0 or account.balance < points:
        raise HTTPException(status_code=402, detail="积分不足")
    account.balance -= points
    account.frozen += points
    account.version += 1
    _record(db, account, kind="reserve", amount=-points, reference_type=reference_type,
            reference_id=reference_id, key=ledger_key)
    return True


def capture(db: Session, user_id: str, points: int, reference_type: str, reference_id: str) -> bool:
    key = f"capture:{reference_type}:{reference_id}"
    if _exists(db, key):
        return False
    account = get_locked_account(db, user_id)
    if account.frozen < points:
        raise RuntimeError("frozen points invariant violated")
    account.frozen -= points
    account.version += 1
    _record(db, account, kind="capture", amount=0, reference_type=reference_type,
            reference_id=reference_id, key=key)
    return True


def release(db: Session, user_id: str, points: int, reference_type: str, reference_id: str,
            note: str | None = None) -> bool:
    key = f"release:{reference_type}:{reference_id}"
    if _exists(db, key):
        return False
    account = get_locked_account(db, user_id)
    if account.frozen < points:
        raise RuntimeError("frozen points invariant violated")
    account.frozen -= points
    account.balance += points
    account.version += 1
    _record(db, account, kind="refund", amount=points, reference_type=reference_type,
            reference_id=reference_id, key=key, note=note)
    return True


def credit(db: Session, user_id: str, points: int, reference_type: str, reference_id: str,
           key: str, note: str | None = None) -> bool:
    ledger_key = f"credit:{key}"
    if _exists(db, ledger_key):
        return False
    account = get_locked_account(db, user_id)
    account.balance += points
    account.version += 1
    _record(db, account, kind="credit", amount=points, reference_type=reference_type,
            reference_id=reference_id, key=ledger_key, note=note)
    return True

