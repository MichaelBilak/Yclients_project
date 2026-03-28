from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()
SYSTEM_SCHEMA = 'system'


# ===================================================================
# Сети и компании
# ===================================================================

class Group(Base):
    __tablename__ = 'groups'

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    access = Column(JSON)

    companies = relationship("Company", back_populates="group")


class Company(Base):
    __tablename__ = 'companies'

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    group_id = Column(Integer, ForeignKey('groups.id'), index=True)

    group = relationship("Group", back_populates="companies")
    services = relationship("Service", back_populates="company")
    staff = relationship("Staff", back_populates="company")
    clients = relationship("Client", back_populates="company")
    appointments = relationship("Appointment", back_populates="company")


# ===================================================================
# Категории услуг и услуги
# ===================================================================

class ServiceCategory(Base):
    __tablename__ = 'service_categories'

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    weight = Column(Integer)
    api_id = Column(String)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)


class Service(Base):
    __tablename__ = 'services'

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    price_min = Column(Float)
    duration = Column(Integer)
    category_title = Column(String, index=True)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)

    company = relationship("Company", back_populates="services")


# ===================================================================
# Должности и сотрудники
# ===================================================================

class StaffPosition(Base):
    __tablename__ = 'staff_positions'

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)


class Staff(Base):
    __tablename__ = 'staff'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    specialization = Column(String)
    position = Column(String, index=True)
    avatar_url = Column(String)
    rating = Column(Float)
    votes_count = Column(Integer)
    bookable = Column(Boolean, default=True)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)

    company = relationship("Company", back_populates="staff")


# ===================================================================
# Клиенты
# ===================================================================

class Client(Base):
    __tablename__ = 'clients'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    phone = Column(String, index=True)
    email = Column(String)
    birth_date = Column(String)
    visits_count = Column(Integer, default=0)
    last_visit_date = Column(String, index=True)
    discount = Column(Float, default=0)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)

    company = relationship("Company", back_populates="clients")


# ===================================================================
# Кассы и склады
# ===================================================================

class Account(Base):
    """Кассы (наличные / безналичные)"""
    __tablename__ = 'accounts'

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    type = Column(Integer, index=True)
    comment = Column(Text)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)


class Storage(Base):
    """Склады"""
    __tablename__ = 'storages'

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    for_services = Column(Boolean, default=False)
    for_sale = Column(Boolean, default=False)
    comment = Column(Text)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)


# ===================================================================
# Товары и категории товаров
# ===================================================================

class GoodCategory(Base):
    __tablename__ = 'good_categories'

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    parent_category_id = Column(Integer, index=True)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)


class Good(Base):
    __tablename__ = 'goods'

    good_id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    cost = Column(Float)
    actual_cost = Column(Float)
    barcode = Column(String, index=True)
    unit_short_title = Column(String)
    category_id = Column(Integer, index=True)
    last_change_date = Column(String, index=True)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)


# ===================================================================
# Записи и транзакции (услуги внутри записи)
# ===================================================================

class Appointment(Base):
    __tablename__ = 'appointments'

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)
    staff_id = Column(Integer, index=True)
    client_id = Column(Integer, index=True)
    date = Column(String, index=True)
    datetime = Column(String)
    create_date = Column(String)
    seance_length = Column(Integer)
    attendance = Column(Integer, default=0, index=True)
    comment = Column(Text)

    company = relationship("Company", back_populates="appointments")
    transactions = relationship("Transaction", back_populates="appointment")


class Transaction(Base):
    """Услуги внутри записи"""
    __tablename__ = 'transactions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    appointment_id = Column(Integer, ForeignKey('appointments.id'), index=True)
    service_id = Column(Integer, index=True)
    service_title = Column(String)
    cost = Column(Float)
    first_cost = Column(Float)
    amount = Column(Integer, default=1)
    company_id = Column(Integer, index=True)

    appointment = relationship("Appointment", back_populates="transactions")


# ===================================================================
# Финансовые транзакции (движения денег)
# ===================================================================

class FinancialTransaction(Base):
    __tablename__ = 'financial_transactions'

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer)
    expense_id = Column(Integer)
    date = Column(String, index=True)
    amount = Column(Float)
    comment = Column(Text)
    account_id = Column(Integer, index=True)
    client_id = Column(Integer, index=True)
    master_id = Column(Integer, index=True)
    record_id = Column(Integer, index=True)
    visit_id = Column(Integer)
    sold_item_id = Column(Integer)
    sold_item_type = Column(String)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)


# ===================================================================
# Товарные транзакции (движения товаров по складам)
# ===================================================================

class GoodTransaction(Base):
    __tablename__ = 'goods_transactions'

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer)
    type_id = Column(Integer)
    good_id = Column(Integer, index=True)
    storage_id = Column(Integer, index=True)
    amount = Column(Float)
    cost_per_unit = Column(Float)
    cost = Column(Float)
    discount = Column(Float)
    master_id = Column(Integer, index=True)
    client_id = Column(Integer, index=True)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)


# ===================================================================
# Комментарии / отзывы
# ===================================================================

class Comment(Base):
    __tablename__ = 'comments'

    id = Column(Integer, primary_key=True)
    type = Column(String)
    master_id = Column(Integer, index=True)
    text = Column(Text)
    date = Column(String, index=True)
    rating = Column(Float)
    user_id = Column(Integer)
    user_name = Column(String)
    record_id = Column(Integer, index=True)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)


# ===================================================================
# Графики работы сотрудников
# ===================================================================

class StaffSchedule(Base):
    __tablename__ = 'staff_schedules'

    id = Column(Integer, primary_key=True, autoincrement=True)
    staff_id = Column(Integer, index=True)
    date = Column(String, index=True)
    slot_from = Column(String)
    slot_to = Column(String)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)


# ===================================================================
# Аналитика YClients (предагрегированные данные)
# ===================================================================

class AnalyticsOverall(Base):
    """Основные показатели компании за период (snapshot)"""
    __tablename__ = 'analytics_overall'

    id = Column(Integer, primary_key=True, autoincrement=True)
    date_from = Column(String, nullable=False, index=True)
    date_to = Column(String, nullable=False, index=True)
    fetched_at = Column(String)

    income_total = Column(Float)
    income_total_prev = Column(Float)
    income_total_change = Column(Float)
    income_services = Column(Float)
    income_services_prev = Column(Float)
    income_goods = Column(Float)
    income_goods_prev = Column(Float)
    income_average = Column(Float)
    income_average_prev = Column(Float)
    income_average_services = Column(Float)
    income_average_services_prev = Column(Float)

    fullness_current = Column(Float)
    fullness_previous = Column(Float)
    fullness_change = Column(Float)

    records_completed = Column(Integer)
    records_pending = Column(Integer)
    records_canceled = Column(Integer)
    records_total = Column(Integer)
    records_total_prev = Column(Integer)
    records_change = Column(Float)

    clients_total = Column(Integer)
    clients_new = Column(Integer)
    clients_new_percent = Column(Float)
    clients_return = Column(Integer)
    clients_return_percent = Column(Float)
    clients_active = Column(Integer)
    clients_lost = Column(Integer)
    clients_lost_percent = Column(Float)

    company_id = Column(Integer, ForeignKey('companies.id'), index=True)


class AnalyticsDailyMetric(Base):
    """Данные по дням: выручка / записи / заполненность"""
    __tablename__ = 'analytics_daily_metrics'

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String, nullable=False, index=True)
    metric_type = Column(String, nullable=False, index=True)
    label = Column(String)
    value = Column(Float)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)


class AnalyticsSourceMetric(Base):
    """Структура записей по источникам"""
    __tablename__ = 'analytics_record_sources'

    id = Column(Integer, primary_key=True, autoincrement=True)
    date_from = Column(String, index=True)
    date_to = Column(String, index=True)
    label = Column(String, nullable=False)
    value = Column(Integer)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)


class AnalyticsStatusMetric(Base):
    """Структура записей по статусам визитов"""
    __tablename__ = 'analytics_record_statuses'

    id = Column(Integer, primary_key=True, autoincrement=True)
    date_from = Column(String, index=True)
    date_to = Column(String, index=True)
    label = Column(String, nullable=False)
    value = Column(Integer)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)


# ===================================================================
# Z-Отчёт
# ===================================================================

class ZReport(Base):
    """Z-отчёт: сводная статистика за день"""
    __tablename__ = 'z_reports'

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_date = Column(String, nullable=False, index=True)

    clients = Column(Integer)
    clients_average = Column(Float)
    records = Column(Integer)
    records_average = Column(Float)
    visit_records = Column(Integer)
    visit_records_average = Column(Float)
    non_visit_records = Column(Integer)
    non_visit_records_average = Column(Float)
    targets = Column(Integer)
    targets_paid = Column(Float)
    goods_count = Column(Integer)
    goods_paid = Column(Float)
    certificates_count = Column(Integer)
    certificates_paid = Column(Float)
    abonement_count = Column(Integer)
    abonement_paid = Column(Float)

    total_accounts = Column(Float)
    total_discount = Column(Float)
    currency = Column(String)

    company_id = Column(Integer, ForeignKey('companies.id'), index=True)


class ZReportPayment(Base):
    """Детализация оплат Z-отчёта"""
    __tablename__ = 'z_report_payments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_date = Column(String, nullable=False, index=True)
    payment_group = Column(String, nullable=False, index=True)
    title = Column(String)
    amount = Column(Float)
    company_id = Column(Integer, ForeignKey('companies.id'), index=True)


# ===================================================================
# Состояние синхронизации
# ===================================================================

class SyncState(Base):
    __tablename__ = 'sync_state'
    __table_args__ = {'schema': SYSTEM_SCHEMA}

    key = Column(String, primary_key=True)
    value = Column(String)
    updated_at = Column(String, index=True)


class SyncRun(Base):
    __tablename__ = 'sync_runs'
    __table_args__ = {'schema': SYSTEM_SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    trigger_type = Column(String, nullable=False, index=True)
    mode = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, index=True)
    initiator = Column(String)
    started_at = Column(String, nullable=False, index=True)
    finished_at = Column(String, index=True)
    log_path = Column(String)
    message = Column(Text)


class SyncStepRun(Base):
    __tablename__ = 'sync_step_runs'
    __table_args__ = {'schema': SYSTEM_SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey(f'{SYSTEM_SCHEMA}.sync_runs.id'), nullable=False, index=True)
    step_name = Column(String, nullable=False, index=True)
    step_key = Column(String, index=True)
    status = Column(String, nullable=False, index=True)
    elapsed_seconds = Column(Float)
    created_at = Column(String, nullable=False, index=True)
