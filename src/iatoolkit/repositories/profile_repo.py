# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.models import User, Company, user_company, ApiKey, UserFeedback
from injector import inject
from iatoolkit.repositories.database_manager import DatabaseManager
from sqlalchemy.orm import joinedload # Para cargar la relación eficientemente


class ProfileRepo:
    @inject
    def __init__(self, db_manager: DatabaseManager):
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
        return self.session.query(Company).filter(Company.short_name == short_name).first()

    def get_companies(self) -> list[Company]:
        return self.session.query(Company).all()

    def get_companies_by_user_identifier(self, user_identifier: str) -> list[Company]:
        """
        Return all the companies to which the user belongs (by email),
        and where also he has admin role in the iat_user_company table.
        """
        return (
            self.session.query(Company)
            .join(user_company, Company.id == user_company.c.company_id)
            .join(User, User.id == user_company.c.user_id)
            .filter(User.email == user_identifier)
            .filter(user_company.c.role == "admin")
            .all()
        )

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

    def create_api_key(self, new_api_key: ApiKey):
        self.session.add(new_api_key)
        self.session.commit()
        return new_api_key


    def get_active_api_key_entry(self, api_key_value: str) -> ApiKey | None:
        """
        search for an active API Key by its value.
        returns the entry if found and is active, None otherwise.
        """
        api_key_entry = (self.session.query(ApiKey).filter
                             (ApiKey.key == api_key_value, ApiKey.is_active == True).first())

        return api_key_entry


    def get_active_api_key_by_company(self, company: Company) -> ApiKey | None:
        return self.session.query(ApiKey)\
                .filter(ApiKey.company == company, ApiKey.is_active == True)\
                .first()




