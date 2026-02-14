# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.models import (User, Company, user_company,
                                           UserFeedback, AccessLog)
from injector import inject
from iatoolkit.repositories.database_manager import DatabaseManager
from sqlalchemy import select, func, and_
from sqlalchemy.exc import OperationalError
import logging


class ProfileRepo:
    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.session = db_manager.get_session()

    def get_user_by_id(self, user_id: int) -> User:
        user = self.session.query(User).filter_by(id=user_id).first()
        return user

    def get_user_by_email(self, email: str) -> User:
        user = self.session.query(User).filter_by(email=email).first()
        return user

    def create_user(self, new_user: User):
        self.session.add(new_user)
        self.session.commit()
        return new_user

    def save_user(self,existing_user: User):
        self.session.add(existing_user)
        self.session.commit()
        return existing_user

    def update_user(self, email, **kwargs):
        user = self.session.query(User).filter_by(email=email).first()
        if not user:
            return None

        # get the fields for update
        for key, value in kwargs.items():
            if hasattr(user, key):  # Asegura que el campo existe en User
                setattr(user, key, value)

        self.session.commit()
        return user             # return updated object

    def verify_user(self, email):
        return self.update_user(email, verified=True)

    def set_temp_code(self, email, temp_code):
        return self.update_user(email, temp_code=temp_code)

    def reset_temp_code(self, email):
        return self.update_user(email, temp_code=None)

    def update_password(self, email, hashed_password):
        return self.update_user(email, password=hashed_password)

    def get_company(self, name: str) -> Company:
        return self.session.query(Company).filter_by(name=name).first()

    def get_company_by_id(self, company_id: int) -> Company:
        return self.session.query(Company).filter_by(id=company_id).first()

    def get_company_by_short_name(self, short_name: str) -> Company:
        # Retry once for transient SSL/network disconnects from pooled connections.
        for attempt in (1, 2):
            try:
                return self.session.query(Company).filter(Company.short_name == short_name).first()
            except OperationalError as e:
                try:
                    self.session.rollback()
                except Exception:
                    pass
                self.db_manager.remove_session()

                if attempt == 1:
                    logging.warning(
                        "Transient DB error resolving company '%s'. Retrying once: %s",
                        short_name,
                        e,
                    )
                    continue
                raise

    def get_companies(self) -> list[Company]:
        return self.session.query(Company).all()

    def get_user_role_in_company(self, company_id, user_id, ):
        stmt = (
            select(user_company.c.role)
            .where(
                user_company.c.user_id == user_id,
                user_company.c.company_id == company_id,
            )
        )
        result = self.session.execute(stmt).scalar_one_or_none()
        return result

    def get_companies_by_user_identifier(self, user_identifier: str) -> list:
        """
        Return all the companies to which the user belongs (by email),
        and the role he has in each company.
        """
        return (
            self.session.query(Company, user_company.c.role)
            .join(user_company, Company.id == user_company.c.company_id)
            .join(User, User.id == user_company.c.user_id)
            .filter(User.email == user_identifier)
            .all()
        )

    def get_company_users_with_details(self, company_short_name: str) -> list[dict]:
        # returns the list of users in the company with their role and last access date

        # subquery for last access date
        last_access_sq = (
            self.session.query(
                AccessLog.user_identifier,
                func.max(AccessLog.timestamp).label("max_ts")
            )
            .filter(AccessLog.company_short_name == company_short_name)
            .group_by(AccessLog.user_identifier)
            .subquery()
        )

        # main query
        stmt = (
            self.session.query(
                User,
                user_company.c.role,
                last_access_sq.c.max_ts
            )
            .join(user_company, User.id == user_company.c.user_id)
            .join(Company, Company.id == user_company.c.company_id)
            .outerjoin(last_access_sq, User.email == last_access_sq.c.user_identifier)
            .filter(Company.short_name == company_short_name)
        )

        results = stmt.all()

        return results

    def create_company(self, new_company: Company):
        company = self.session.query(Company).filter_by(short_name=new_company.short_name).first()
        if company:
            if company.parameters != new_company.parameters:
                company.parameters = new_company.parameters
        else:
            # Si la compañía no existe, la añade a la sesión.
            self.session.add(new_company)
            company = new_company

        self.session.commit()
        return company

    def save_feedback(self, feedback: UserFeedback):
        self.session.add(feedback)
        self.session.commit()
        return feedback
