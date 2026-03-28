"""
API сервер для предоставления данных YClients в табличном формате
"""
import threading
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from models import (
    Group, Company, ServiceCategory, Service, StaffPosition, Staff, Client,
    Account, Storage, GoodCategory, Good,
    Appointment, Transaction, FinancialTransaction, GoodTransaction,
    Comment, StaffSchedule,
)
from database import init_database, get_db
from config import (
    API_HOST,
    API_PORT,
    DB_HOST,
    DB_PORT,
    DB_NAME,
    DB_USER,
    DB_PASSWORD,
    SYNC_API_TOKEN,
)
import pandas as pd
from typing import Literal, Optional
from sync_orchestrator import get_sync_status, run_sync_job

init_database(DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD)

app = FastAPI(
    title="YClients BI System API",
    description="API для получения данных YClients в табличном формате",
    version="3.0.0"
)


@app.get("/")
async def root():
    return {
        "message": "YClients BI System API",
        "endpoints": {
            "/groups": "Сети",
            "/companies": "Компании",
            "/service_categories": "Категории услуг",
            "/services": "Услуги",
            "/staff_positions": "Должности",
            "/staff": "Сотрудники",
            "/clients": "Клиенты",
            "/accounts": "Кассы",
            "/storages": "Склады",
            "/good_categories": "Категории товаров",
            "/goods": "Товары",
            "/appointments": "Записи (визиты)",
            "/transactions": "Услуги внутри записей",
            "/financial_transactions": "Финансовые транзакции",
            "/goods_transactions": "Товарные транзакции",
            "/comments": "Комментарии / отзывы",
            "/staff_schedules": "Графики работы",
            "/stats": "Общая статистика",
            "/export/csv/{table}": "Экспорт таблицы в CSV",
        }
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


def require_sync_token(x_sync_token: str | None = Header(default=None)):
    if not SYNC_API_TOKEN:
        return
    if x_sync_token != SYNC_API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid sync token")


# ---------------------------------------------------------------
# Groups
# ---------------------------------------------------------------

@app.get("/groups")
async def api_groups(db: Session = Depends(get_db)):
    try:
        groups = db.query(Group).all()
        data = [{
            "id": g.id, "title": g.title,
            "companies_count": db.query(Company).filter(Company.group_id == g.id).count(),
        } for g in groups]
        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Companies
# ---------------------------------------------------------------

@app.get("/companies")
async def api_companies(group_id: Optional[int] = None, db: Session = Depends(get_db)):
    try:
        q = db.query(Company)
        if group_id:
            q = q.filter(Company.group_id == group_id)
        companies = q.all()

        data = [{
            "id": c.id, "title": c.title, "group_id": c.group_id,
        } for c in companies]
        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Service Categories
# ---------------------------------------------------------------

@app.get("/service_categories")
async def api_service_categories(company_id: Optional[int] = None,
                                  db: Session = Depends(get_db)):
    try:
        q = db.query(ServiceCategory)
        if company_id:
            q = q.filter(ServiceCategory.company_id == company_id)
        items = q.all()
        data = [{
            "id": i.id, "title": i.title, "weight": i.weight,
            "api_id": i.api_id, "company_id": i.company_id,
        } for i in items]
        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Services
# ---------------------------------------------------------------

@app.get("/services")
async def api_services(
    company_id: Optional[int] = None,
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    db: Session = Depends(get_db),
):
    try:
        q = db.query(Service)
        if company_id:
            q = q.filter(Service.company_id == company_id)
        if category:
            q = q.filter(Service.category_title == category)
        if min_price is not None:
            q = q.filter(Service.price_min >= min_price)
        if max_price is not None:
            q = q.filter(Service.price_min <= max_price)

        services = q.all()
        data = [{
            "id": s.id, "title": s.title,
            "price_min": s.price_min,
            "duration_sec": s.duration,
            "duration_min": round(s.duration / 60, 1) if s.duration else None,
            "category": s.category_title, "company_id": s.company_id,
        } for s in services]

        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Staff Positions
# ---------------------------------------------------------------

@app.get("/staff_positions")
async def api_staff_positions(company_id: Optional[int] = None,
                               db: Session = Depends(get_db)):
    try:
        q = db.query(StaffPosition)
        if company_id:
            q = q.filter(StaffPosition.company_id == company_id)
        items = q.all()
        data = [{"id": i.id, "title": i.title, "company_id": i.company_id} for i in items]
        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Staff
# ---------------------------------------------------------------

@app.get("/staff")
async def api_staff(company_id: Optional[int] = None, db: Session = Depends(get_db)):
    try:
        q = db.query(Staff)
        if company_id:
            q = q.filter(Staff.company_id == company_id)

        staff = q.all()
        data = [{
            "id": s.id, "name": s.name, "specialization": s.specialization,
            "position": s.position, "rating": s.rating,
            "votes_count": s.votes_count, "bookable": s.bookable,
            "company_id": s.company_id,
        } for s in staff]
        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Clients
# ---------------------------------------------------------------

@app.get("/clients")
async def api_clients(
    company_id: Optional[int] = None,
    min_visits: Optional[int] = None,
    db: Session = Depends(get_db),
):
    try:
        q = db.query(Client)
        if company_id:
            q = q.filter(Client.company_id == company_id)
        if min_visits is not None:
            q = q.filter(Client.visits_count >= min_visits)

        clients = q.all()
        data = [{
            "id": c.id, "name": c.name, "phone": c.phone, "email": c.email,
            "birth_date": c.birth_date, "visits_count": c.visits_count,
            "last_visit_date": c.last_visit_date, "discount": c.discount,
            "company_id": c.company_id,
        } for c in clients]
        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Accounts (cash registers)
# ---------------------------------------------------------------

@app.get("/accounts")
async def api_accounts(company_id: Optional[int] = None,
                        db: Session = Depends(get_db)):
    try:
        q = db.query(Account)
        if company_id:
            q = q.filter(Account.company_id == company_id)
        items = q.all()
        data = [{
            "id": i.id, "title": i.title, "type": i.type,
            "comment": i.comment, "company_id": i.company_id,
        } for i in items]
        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Storages (warehouses)
# ---------------------------------------------------------------

@app.get("/storages")
async def api_storages(company_id: Optional[int] = None,
                        db: Session = Depends(get_db)):
    try:
        q = db.query(Storage)
        if company_id:
            q = q.filter(Storage.company_id == company_id)
        items = q.all()
        data = [{
            "id": i.id, "title": i.title,
            "for_services": i.for_services, "for_sale": i.for_sale,
            "comment": i.comment, "company_id": i.company_id,
        } for i in items]
        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Good Categories
# ---------------------------------------------------------------

@app.get("/good_categories")
async def api_good_categories(company_id: Optional[int] = None,
                               db: Session = Depends(get_db)):
    try:
        q = db.query(GoodCategory)
        if company_id:
            q = q.filter(GoodCategory.company_id == company_id)
        items = q.all()
        data = [{
            "id": i.id, "title": i.title,
            "parent_category_id": i.parent_category_id,
            "company_id": i.company_id,
        } for i in items]
        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Goods (products)
# ---------------------------------------------------------------

@app.get("/goods")
async def api_goods(company_id: Optional[int] = None,
                     category_id: Optional[int] = None,
                     db: Session = Depends(get_db)):
    try:
        q = db.query(Good)
        if company_id:
            q = q.filter(Good.company_id == company_id)
        if category_id:
            q = q.filter(Good.category_id == category_id)
        items = q.all()
        data = [{
            "good_id": i.good_id, "title": i.title,
            "cost": i.cost, "actual_cost": i.actual_cost,
            "barcode": i.barcode, "unit": i.unit_short_title,
            "category_id": i.category_id, "company_id": i.company_id,
        } for i in items]
        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------

@app.get("/appointments")
async def api_appointments(
    company_id: Optional[int] = None,
    staff_id: Optional[int] = None,
    client_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
):
    try:
        q = db.query(Appointment)
        if company_id:
            q = q.filter(Appointment.company_id == company_id)
        if staff_id:
            q = q.filter(Appointment.staff_id == staff_id)
        if client_id:
            q = q.filter(Appointment.client_id == client_id)
        if date_from:
            q = q.filter(Appointment.date >= date_from)
        if date_to:
            q = q.filter(Appointment.date <= date_to)

        appointments = q.all()
        data = [{
            "id": a.id, "company_id": a.company_id,
            "staff_id": a.staff_id, "client_id": a.client_id,
            "date": a.date, "datetime": a.datetime,
            "create_date": a.create_date, "seance_length": a.seance_length,
            "attendance": a.attendance, "comment": a.comment,
        } for a in appointments]
        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Transactions (services inside appointments)
# ---------------------------------------------------------------

@app.get("/transactions")
async def api_transactions(
    company_id: Optional[int] = None,
    appointment_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    try:
        q = db.query(Transaction)
        if company_id:
            q = q.filter(Transaction.company_id == company_id)
        if appointment_id:
            q = q.filter(Transaction.appointment_id == appointment_id)

        txns = q.all()
        data = [{
            "id": t.id, "appointment_id": t.appointment_id,
            "service_id": t.service_id, "service_title": t.service_title,
            "cost": t.cost, "first_cost": t.first_cost,
            "amount": t.amount, "company_id": t.company_id,
        } for t in txns]
        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Financial Transactions
# ---------------------------------------------------------------

@app.get("/financial_transactions")
async def api_financial_transactions(
    company_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
):
    try:
        q = db.query(FinancialTransaction)
        if company_id:
            q = q.filter(FinancialTransaction.company_id == company_id)
        if date_from:
            q = q.filter(FinancialTransaction.date >= date_from)
        if date_to:
            q = q.filter(FinancialTransaction.date <= date_to)

        items = q.all()
        data = [{
            "id": i.id, "document_id": i.document_id,
            "expense_id": i.expense_id, "date": i.date,
            "amount": i.amount, "comment": i.comment,
            "account_id": i.account_id, "client_id": i.client_id,
            "master_id": i.master_id, "record_id": i.record_id,
            "visit_id": i.visit_id, "sold_item_id": i.sold_item_id,
            "sold_item_type": i.sold_item_type, "company_id": i.company_id,
        } for i in items]
        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Goods Transactions
# ---------------------------------------------------------------

@app.get("/goods_transactions")
async def api_goods_transactions(
    company_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
):
    try:
        q = db.query(GoodTransaction)
        if company_id:
            q = q.filter(GoodTransaction.company_id == company_id)
        items = q.all()
        data = [{
            "id": i.id, "document_id": i.document_id,
            "type_id": i.type_id, "good_id": i.good_id,
            "storage_id": i.storage_id, "amount": i.amount,
            "cost_per_unit": i.cost_per_unit, "cost": i.cost,
            "discount": i.discount, "master_id": i.master_id,
            "client_id": i.client_id, "company_id": i.company_id,
        } for i in items]
        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Comments / Reviews
# ---------------------------------------------------------------

@app.get("/comments")
async def api_comments(
    company_id: Optional[int] = None,
    staff_id: Optional[int] = None,
    min_rating: Optional[float] = None,
    db: Session = Depends(get_db),
):
    try:
        q = db.query(Comment)
        if company_id:
            q = q.filter(Comment.company_id == company_id)
        if staff_id:
            q = q.filter(Comment.master_id == staff_id)
        if min_rating is not None:
            q = q.filter(Comment.rating >= min_rating)
        items = q.all()
        data = [{
            "id": i.id, "type": i.type, "master_id": i.master_id,
            "text": i.text, "date": i.date, "rating": i.rating,
            "user_id": i.user_id, "user_name": i.user_name,
            "record_id": i.record_id, "company_id": i.company_id,
        } for i in items]
        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Staff Schedules
# ---------------------------------------------------------------

@app.get("/staff_schedules")
async def api_staff_schedules(
    company_id: Optional[int] = None,
    staff_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
):
    try:
        q = db.query(StaffSchedule)
        if company_id:
            q = q.filter(StaffSchedule.company_id == company_id)
        if staff_id:
            q = q.filter(StaffSchedule.staff_id == staff_id)
        if date_from:
            q = q.filter(StaffSchedule.date >= date_from)
        if date_to:
            q = q.filter(StaffSchedule.date <= date_to)

        items = q.all()
        data = [{
            "id": i.id, "staff_id": i.staff_id,
            "date": i.date, "slot_from": i.slot_from,
            "slot_to": i.slot_to, "company_id": i.company_id,
        } for i in items]
        return {"total": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Stats
# ---------------------------------------------------------------

@app.get("/stats")
async def api_stats(db: Session = Depends(get_db)):
    try:
        revenue = db.query(func.sum(Transaction.cost * Transaction.amount)).scalar() or 0
        fin_income = db.query(func.sum(FinancialTransaction.amount)).filter(
            FinancialTransaction.amount > 0
        ).scalar() or 0

        appointments_total = db.query(Appointment).count()
        attended = db.query(Appointment).filter(Appointment.attendance > 0).count()

        return {
            "groups": db.query(Group).count(),
            "companies": db.query(Company).count(),
            "service_categories": db.query(ServiceCategory).count(),
            "services": db.query(Service).count(),
            "staff_positions": db.query(StaffPosition).count(),
            "staff": db.query(Staff).count(),
            "clients": db.query(Client).count(),
            "accounts": db.query(Account).count(),
            "storages": db.query(Storage).count(),
            "good_categories": db.query(GoodCategory).count(),
            "goods": db.query(Good).count(),
            "appointments": appointments_total,
            "appointments_attended": attended,
            "transactions": db.query(Transaction).count(),
            "financial_transactions": db.query(FinancialTransaction).count(),
            "goods_transactions": db.query(GoodTransaction).count(),
            "comments": db.query(Comment).count(),
            "staff_schedule_slots": db.query(StaffSchedule).count(),
            "total_revenue": round(revenue, 2),
            "financial_income": round(fin_income, 2),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------
# Sync Trigger (ручной запуск синхронизации)
# ---------------------------------------------------------------


class SyncTriggerRequest(BaseModel):
    mode: Literal['incremental', 'full'] = 'incremental'
    initiator: str = 'dashboard'


def _run_sync_in_background(mode: str, initiator: str):
    run_sync_job(mode=mode, trigger_type='manual', initiator=initiator)


@app.post("/sync/trigger")
async def trigger_sync(payload: SyncTriggerRequest, _: None = Depends(require_sync_token)):
    status = get_sync_status()
    if status.get('running'):
        return {"status": "already_running", "message": "Синхронизация уже запущена", "detail": status}

    thread = threading.Thread(
        target=_run_sync_in_background,
        kwargs={'mode': payload.mode, 'initiator': payload.initiator},
        daemon=True,
    )
    thread.start()

    return {
        "status": "started",
        "message": "Синхронизация запущена в фоне",
        "mode": payload.mode,
        "initiator": payload.initiator,
    }


@app.get("/sync/status")
async def sync_status(_: None = Depends(require_sync_token)):
    return get_sync_status()


# ---------------------------------------------------------------
# CSV Export (универсальный)
# ---------------------------------------------------------------

TABLE_MAP = {
    "groups": Group,
    "companies": Company,
    "service_categories": ServiceCategory,
    "services": Service,
    "staff_positions": StaffPosition,
    "staff": Staff,
    "clients": Client,
    "accounts": Account,
    "storages": Storage,
    "good_categories": GoodCategory,
    "goods": Good,
    "appointments": Appointment,
    "transactions": Transaction,
    "financial_transactions": FinancialTransaction,
    "goods_transactions": GoodTransaction,
    "comments": Comment,
    "staff_schedules": StaffSchedule,
}


@app.get("/export/csv/{table_name}")
async def export_csv(table_name: str, db: Session = Depends(get_db)):
    if table_name not in TABLE_MAP:
        raise HTTPException(
            status_code=404,
            detail=f"Таблица '{table_name}' не найдена. Доступные: {list(TABLE_MAP.keys())}"
        )

    try:
        model = TABLE_MAP[table_name]
        rows = db.query(model).all()

        columns = [c.key for c in model.__table__.columns]
        data = [{col: getattr(row, col) for col in columns} for row in rows]

        df = pd.DataFrame(data)
        csv_content = df.to_csv(index=False, encoding='utf-8-sig')

        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={table_name}.csv"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)
