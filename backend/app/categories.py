"""Stable category appearance and reversible lifecycle rules."""

from calendar import monthrange
from datetime import date, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.app.models import Category, Transaction


CATEGORY_PALETTE = (
    "#326B50", "#B65F3C", "#315C96", "#8B5BA7", "#A46A19", "#217A82",
    "#A64C6E", "#566C31", "#98522D", "#4F60A9", "#8D7031", "#27836A",
    "#974F92", "#B04D4D", "#487D36", "#4574A4", "#A45D75", "#677C26",
    "#85579C", "#A86931", "#437879", "#B05C54", "#5D689A", "#82733B",
)


def suggested_color(session: Session) -> str:
    used = set(session.scalars(select(Category.color)).all())
    for color in CATEGORY_PALETTE:
        if color not in used:
            return color
    # More than 24 categories: keep assigning a persistent, deterministic hex value.
    index = len(used)
    while True:
        hue = (index * 137.508) % 360
        import colorsys
        r, g, b = colorsys.hls_to_rgb(hue / 360, .39, .48)
        color = f"#{round(r*255):02X}{round(g*255):02X}{round(b*255):02X}"
        if color not in used:
            return color
        index += 1


def category_visible_in_budget(category: Category, day: date) -> bool:
    return category.is_active or bool(category.archived_on and day < category.archived_on) or bool(category.visible_until and day <= category.visible_until)


def archive_preview(session: Session, category: Category, on: date) -> dict:
    from backend.app.domain import active_budget

    financial_date = func.coalesce(Transaction.settled_date, Transaction.transaction_date)
    active = active_budget(session, category.id, on) if category.kind == "expense" else None
    start = active[1] if active else on.replace(day=1)
    end = active[2] if active else date(on.year, on.month, monthrange(on.year, on.month)[1]) + timedelta(days=1)
    current = session.execute(select(
        func.count(Transaction.id),
        func.coalesce(func.sum(case((Transaction.kind == "refund", -Transaction.amount), else_=Transaction.amount)), 0),
    ).where(Transaction.category_id == category.id, Transaction.kind.in_(["expense", "refund"]),
            Transaction.status == "settled", Transaction.deleted_at.is_(None),
            financial_date >= start, financial_date < end)).one()
    historical_count = session.scalar(select(func.count(Transaction.id)).where(Transaction.category_id == category.id)) or 0
    return {"category_id": str(category.id), "name": category.name,
            "current_spending_count": int(current[0]), "current_spent": current[1],
            "transaction_count": historical_count, "period_start": start,
            "period_end": end - timedelta(days=1),
            "visible_until": end - timedelta(days=1) if current[0] else None}


def archive_category(session: Session, category_id: UUID, on: date) -> dict:
    category = session.scalar(select(Category).where(Category.id == category_id).with_for_update())
    if not category:
        raise HTTPException(404, "Categoria não encontrada")
    if not category.is_active:
        raise HTTPException(409, "Categoria já está arquivada")
    preview = archive_preview(session, category, on)
    category.is_active = False
    category.archived_on = on
    category.visible_until = preview["visible_until"]
    session.flush()
    return preview


def restore_category(session: Session, category_id: UUID) -> Category:
    category = session.scalar(select(Category).where(Category.id == category_id).with_for_update())
    if not category:
        raise HTTPException(404, "Categoria não encontrada")
    if category.is_active:
        raise HTTPException(409, "Categoria já está ativa")
    category.is_active = True
    category.archived_on = None
    category.visible_until = None
    session.flush()
    return category
