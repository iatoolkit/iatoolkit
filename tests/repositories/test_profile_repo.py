# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit
# Todos los derechos reservados.
# En trámite de registro en el Registro de Propiedad Intelectual de Chile.

import pytest
from repositories.database_manager import DatabaseManager
from repositories.models import User, Company, UserFeedback
from repositories.profile_repo import ProfileRepo


class TestProfileRepo:
    def setup_method(self):
        self.db_manager = DatabaseManager('sqlite:///:memory:')
        self.db_manager.create_all()
        self.session = self.db_manager.get_session()
        self.repo = ProfileRepo(self.db_manager)

        self.user = User(email='fernando@opensoft.cl',
                         first_name='Fernando',
                         last_name='Libedinsky',
                         rut='2978637-2', password='123')

        self.company = Company(name='opensoft', short_name='open')

    def test_get_user_by_id_when_not_found(self):
        result = self.repo.get_user_by_id(2)
        assert result is None

    def test_get_user_by_id_when_success(self):
        self.session.add(self.user)
        result = self.repo.get_user_by_id(1)
        assert result == self.user

    def test_get_user_by_email_when_not_found(self):
        result = self.repo.get_user_by_email('fl@opensoft')
        assert result is None

    def test_get_user_by_email_when_success(self):
        self.session.add(self.user)
        result = self.repo.get_user_by_email('fernando@opensoft.cl')
        assert result == self.user

    def test_get_user_by_rut_when_success(self):
        self.session.add(self.user)
        result = self.repo.get_user_by_rut('2978637-2')
        assert result == self.user

    def test_create_user_when_ok(self):
        new_user = self.repo.create_user(self.user)
        assert new_user.id == 1

    def test_save_and_update_user_when_ok(self):
        new_user = self.repo.create_user(self.user)
        new_user.first_name = 'fernando'

        updated_user = self.repo.save_user(new_user)
        assert updated_user.id == 1

    def test_update_user_when_not_exist(self):
        user = self.repo.update_user(self.user.email, first_name='Fernando')
        assert user == None

    def test_verify_user_when_ok(self):
        self.session.add(self.user)
        user = self.repo.verify_user(self.user.email)
        assert user.verified == True

    def test_set_temp_code_when_ok(self):
        self.session.add(self.user)
        temp_code = 'CCGT'
        user = self.repo.set_temp_code(self.user.email,temp_code)

        assert user.temp_code == temp_code

    def test_reset_temp_code_when_ok(self):
        self.session.add(self.user)
        user = self.repo.reset_temp_code(self.user.email)

        assert user.temp_code == None

    def test_update_password_when_ok(self):
        self.session.add(self.user)
        hashed_password = 'ggdvXz'
        user = self.repo.update_password(self.user.email, hashed_password)

        assert user.password == hashed_password

    def test_get_company_when_no_exist(self):
        assert self.repo.get_company('opensoft') == None

    def test_get_company_when_ok(self):
        self.session.add(self.company)
        assert self.repo.get_company('opensoft') == self.company
        assert self.repo.get_company_by_short_name('open') == self.company

    def test_get_company_by_id_when_not_found(self):
        result = self.repo.get_company_by_id(999)

        assert result is None

    def test_get_company_by_id_when_success(self):
        self.session.add(self.company)

        result = self.repo.get_company_by_id(1)
        assert result == self.company

    def test_get_companies_when_no_companies_exist(self):
        result = self.repo.get_companies()
        assert result == []

    def test_get_companies_when_companies_exist(self):
        company_opensoft = Company(name='Opensoft', short_name='open')
        company_testlabs = Company(name='TestLabs', short_name='test')
        self.session.add(company_opensoft)
        self.session.add(company_testlabs)
        self.session.commit()

        result = self.repo.get_companies()

        assert len(result) == 2
        assert result[0].name == 'Opensoft'
        assert result[1].name == 'TestLabs'

    def test_create_company_when_company_exists(self):
        self.session.add(self.company)

        result = self.repo.create_company(Company(name='opensoft'))

        assert result.id == self.company.id
        assert result.name == self.company.name

    def test_create_company_when_new_company(self):
        result = self.repo.create_company(Company(name='NewCompany', short_name='new'))

        assert result.id is not None
        assert result.name == 'NewCompany'

    def test_save_feedback_when_ok(self):
        company = self.repo.create_company(Company(name='maxxa', short_name='maxxa'))
        feedback = UserFeedback(company_id=company.id,
                                external_user_id='flibe',
                                message='feedback message',
                                rating=4)
        new_feed = self.repo.save_feedback(feedback)
        assert new_feed.message == 'feedback message'
        assert new_feed.rating == 4

