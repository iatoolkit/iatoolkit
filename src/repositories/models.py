# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from sqlalchemy import Column, Integer, String, DateTime, Enum, Text, JSON, Boolean, ForeignKey, Table
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import relationship, class_mapper, declarative_base
from datetime import datetime
from pgvector.sqlalchemy import Vector
from enum import Enum as PyEnum
import secrets
import enum


# base class for the ORM
class Base(DeclarativeBase):
    pass

# relation table for many-to-many relationship between companies and users
user_company = Table('iat_user_company',
                     Base.metadata,
                    Column('user_id', Integer,
                           ForeignKey('iat_users.id', ondelete='CASCADE'),
                                primary_key=True),
                     Column('company_id', Integer,
                            ForeignKey('iat_companies.id',ondelete='CASCADE'),
                                primary_key=True),
                     Column('is_active', Boolean, default=True),
                     Column('role', String(50), default='user'),  # Para manejar roles por empresa
                     Column('created_at', DateTime, default=datetime.now)
                     )

class ApiKey(Base):
    """Represents an API key for a company to authenticate against the system."""
    __tablename__ = 'iat_api_keys'

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('iat_companies.id', ondelete='CASCADE'), nullable=False)
    key = Column(String(128), unique=True, nullable=False, index=True) # La API Key en sí
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    last_used_at = Column(DateTime, nullable=True) # Opcional: para rastrear uso

    company = relationship("Company", back_populates="api_keys")


class Company(Base):
    """Represents a company or tenant in the multi-tenant system."""
    __tablename__ = 'iat_companies'

    id = Column(Integer, primary_key=True)
    short_name = Column(String(20), nullable=False, unique=True, index=True)
    name = Column(String(256), nullable=False)

    # encrypted api-key
    openai_api_key = Column(String, nullable=True)
    gemini_api_key = Column(String, nullable=True)

    logo_file = Column(String(128), nullable=True, default='')
    parameters = Column(JSON, nullable=True, default={})
    created_at = Column(DateTime, default=datetime.now)
    allow_jwt = Column(Boolean, default=False, nullable=True)

    documents = relationship("Document",
                             back_populates="company",
                             cascade="all, delete-orphan",
                             lazy='dynamic')
    functions = relationship("Function",
                           back_populates="company",
                           cascade="all, delete-orphan")
    vsdocs = relationship("VSDoc",
                          back_populates="company",
                          cascade="all, delete-orphan")
    llm_queries = relationship("LLMQuery",
                               back_populates="company",
                               cascade="all, delete-orphan")
    users = relationship("User",
                         secondary=user_company,
                         back_populates="companies")
    api_keys = relationship("ApiKey",
                            back_populates="company",
                            cascade="all, delete-orphan")

    tasks = relationship("Task", back_populates="company")
    feedbacks = relationship("UserFeedback",
                               back_populates="company",
                               cascade="all, delete-orphan")
    prompts = relationship("Prompt",
                             back_populates="company",
                             cascade="all, delete-orphan")

    def to_dict(self):
        return {column.key: getattr(self, column.key) for column in class_mapper(self.__class__).columns}

# users with rights to use this app
class User(Base):
    """Represents an IAToolkit user who can be associated with multiple companies."""
    __tablename__ = 'iat_users'

    id = Column(Integer, primary_key=True)
    email = Column(String(80), unique=True, nullable=False)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    password = Column(String, nullable=False)
    verified = Column(Boolean, nullable=False, default=False)
    verification_url = Column(String, nullable=True)
    temp_code = Column(String, nullable=True)

    companies = relationship(
        "Company",
        secondary=user_company,
        back_populates="users",
        cascade="all",
        passive_deletes=True,
        lazy='dynamic'
    )

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'created_at': str(self.created_at),
            'verified': self.verified,
            'companies': [company.to_dict() for company in self.companies]
        }

class Function(Base):
    """Represents a custom or system function that the LLM can call (tool)."""
    __tablename__ = 'iat_functions'

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer,
                        ForeignKey('iat_companies.id',ondelete='CASCADE'),
                        nullable=True)
    name = Column(String(255), nullable=False)
    system_function = Column(Boolean, default=False)
    description = Column(Text, nullable=False)
    parameters = Column(JSON, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

    company = relationship('Company', back_populates='functions')

    def to_dict(self):
        return {column.key: getattr(self, column.key) for column in class_mapper(self.__class__).columns}


class Document(Base):
    """Represents a file or document uploaded by a company for context."""
    __tablename__ = 'iat_documents'

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey('iat_companies.id',
                    ondelete='CASCADE'), nullable=False)
    filename = Column(String(256), nullable=False, index=True)
    content = Column(Text, nullable=False)
    content_b64 = Column(Text, nullable=False)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    company = relationship("Company", back_populates="documents")

    def to_dict(self):
        return {column.key: getattr(self, column.key) for column in class_mapper(self.__class__).columns}


class LLMQuery(Base):
    """Logs a query made to the LLM, including input, output, and metadata."""
    __tablename__ = 'iat_queries'

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('iat_companies.id',
                            ondelete='CASCADE'), nullable=False)
    user_identifier = Column(String(128), nullable=False)
    task_id = Column(Integer, default=0, nullable=True)
    query = Column(Text, nullable=False)
    output = Column(Text, nullable=False)
    response = Column(JSON, nullable=True, default={})
    valid_response = Column(Boolean, nullable=False, default=False)
    function_calls = Column(JSON, nullable=True, default={})
    stats = Column(JSON, default={})
    answer_time = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

    company = relationship("Company", back_populates="llm_queries")
    tasks = relationship("Task", back_populates="llm_query")

    def to_dict(self):
        return {column.key: getattr(self, column.key) for column in class_mapper(self.__class__).columns}


class VSDoc(Base):
    """Stores a text chunk and its corresponding vector embedding for similarity search."""
    __tablename__ = "iat_vsdocs"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('iat_companies.id',
                    ondelete='CASCADE'), nullable=False)
    document_id = Column(Integer, ForeignKey('iat_documents.id',
                        ondelete='CASCADE'), nullable=False)
    text = Column(Text, nullable=False)
    embedding = Column(Vector(384), nullable=False)  # Ajusta la dimensión si es necesario

    company = relationship("Company", back_populates="vsdocs")

    def to_dict(self):
        return {column.key: getattr(self, column.key) for column in class_mapper(self.__class__).columns}

class TaskStatus(PyEnum):
    """Enumeration for the possible statuses of a Task."""
    pendiente = "pendiente"  # task created and waiting to be executed.
    ejecutado = "ejecutado"  # the IA algorithm has been executed.
    aprobada = "aprobada"  # validated and approved by human.
    rechazada = "rechazada"  # validated and rejected by human.
    fallida = "fallida"  # error executing the IA algorithm.

class TaskType(Base):
    """Defines a type of task that can be executed, including its prompt template."""
    __tablename__ = 'iat_task_types'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    prompt_template = Column(String(100), nullable=True)  # Plantilla de prompt por defecto.
    template_args = Column(JSON, nullable=True)  # Argumentos/prefijos de configuración para el template.

class Task(Base):
    """Represents an asynchronous task to be executed by the system, often involving an LLM."""
    __tablename__ = 'iat_tasks'

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("iat_companies.id"))

    user_id = Column(Integer, nullable=True, default=0)
    task_type_id = Column(Integer, ForeignKey('iat_task_types.id'), nullable=False)
    status = Column(Enum(TaskStatus, name="task_status_enum"),
                    default=TaskStatus.pendiente, nullable=False)
    client_data = Column(JSON, nullable=True, default={})
    company_task_id = Column(Integer, nullable=True, default=0)
    execute_at = Column(DateTime, default=datetime.now, nullable=True)
    llm_query_id = Column(Integer, ForeignKey('iat_queries.id'), nullable=True)
    callback_url = Column(String(512), default=None, nullable=True)
    files = Column(JSON, default=[], nullable=True)

    review_user = Column(String(128), nullable=True, default='')
    review_date = Column(DateTime, nullable=True)
    comment = Column(Text, nullable=True)
    approved = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)

    task_type = relationship("TaskType")
    llm_query = relationship("LLMQuery", back_populates="tasks", uselist=False)
    company = relationship("Company", back_populates="tasks")

class UserFeedback(Base):
    """Stores feedback and ratings submitted by users for specific interactions."""
    __tablename__ = 'iat_feedback'

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('iat_companies.id',
                                            ondelete='CASCADE'), nullable=False)
    local_user_id = Column(Integer, default=0, nullable=True)
    external_user_id = Column(String(128), default='', nullable=True)
    message = Column(Text, nullable=False)
    rating = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    company = relationship("Company", back_populates="feedbacks")


class PromptCategory(Base):
    """Represents a category to group and organize prompts."""
    __tablename__ = 'iat_prompt_categories'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    order = Column(Integer, nullable=False, default=0)
    company_id = Column(Integer, ForeignKey('iat_companies.id'), nullable=False)

    prompts = relationship("Prompt", back_populates="category", order_by="Prompt.order")

    def __repr__(self):
        return f"<PromptCategory(name='{self.name}', order={self.order})>"


class Prompt(Base):
    """Represents a system or user-defined prompt template for the LLM."""
    __tablename__ = 'iat_prompt'

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('iat_companies.id',
                                            ondelete='CASCADE'), nullable=True)
    name = Column(String(64), nullable=False)
    description = Column(String(256), nullable=False)
    filename = Column(String(256), nullable=False)
    active = Column(Boolean, default=True)
    is_system_prompt = Column(Boolean, default=False)
    order = Column(Integer, nullable=False, default=0)  # Nuevo campo para el orden
    category_id = Column(Integer, ForeignKey('iat_prompt_categories.id'), nullable=True)
    parameters = Column(JSON, nullable=True, default={})
    custom_fields = Column(JSON, nullable=False, default=[])

    created_at = Column(DateTime, default=datetime.now)

    company = relationship("Company", back_populates="prompts")
    category = relationship("PromptCategory", back_populates="prompts")
