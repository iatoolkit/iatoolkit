# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import (User, Company, UserFeedback,
                                           user_company, AccessLog)
from iatoolkit.repositories.profile_repo import ProfileRepo
from datetime import datetime
from unittest.mock import MagicMock
from sqlalchemy.exc import OperationalError


class TestProfileRepo:
    def setup_method(self):
        self.db_manager = DatabaseManager('sqlite:///:memory:')
        self.db_manager.create_all()
        self.session = self.db_manager.get_session()
        self.repo = ProfileRepo(self.db_manager)

        self.user = User(email='fernando@opensoft.cl',
                         first_name='Fernando',
                         last_name='Libedinsky',
                         password='123')

        self.company = Company(name='opensoft', short_name='open')

    def test_get_user_by_id_when_not_found(self):
        result = self.repo.get_user_by_id(2)
        assert result is None

    def test_get_user_by_id_when_success(self):
        self.session.add(self.user)
        self.session.commit()
        result = self.repo.get_user_by_id(1)
        assert result == self.user

    def test_get_user_by_email_when_not_found(self):
        result = self.repo.get_user_by_email('fl@opensoft')
        assert result is None

    def test_get_user_by_email_when_success(self):
        self.session.add(self.user)
        self.session.commit()
        result = self.repo.get_user_by_email('fernando@opensoft.cl')
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
        self.session.commit()
        user = self.repo.verify_user(self.user.email)
        assert user.verified == True

    def test_set_temp_code_when_ok(self):
        self.session.add(self.user)
        self.session.commit()
        temp_code = 'CCGT'
        user = self.repo.set_temp_code(self.user.email,temp_code)

        assert user.temp_code == temp_code

    def test_reset_temp_code_when_ok(self):
        self.session.add(self.user)
        self.session.commit()
        user = self.repo.reset_temp_code(self.user.email)

        assert user.temp_code == None

    def test_update_password_when_ok(self):
        self.session.add(self.user)
        self.session.commit()
        hashed_password = 'ggdvXz'
        user = self.repo.update_password(self.user.email, hashed_password)

        assert user.password == hashed_password

    def test_get_company_when_no_exist(self):
        assert self.repo.get_company('opensoft') == None

    def test_get_company_when_ok(self):
        self.session.add(self.company)
        self.session.commit()
        assert self.repo.get_company('opensoft') == self.company
        assert self.repo.get_company_by_short_name('open') == self.company

    def test_get_company_by_id_when_not_found(self):
        result = self.repo.get_company_by_id(999)

        assert result is None

    def test_get_company_by_id_when_success(self):
        self.session.add(self.company)
        self.session.commit()

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

    def test_get_companies_by_user_identifier_when_no_companies(self):
        self.session.add(self.user)
        self.session.commit()

        results = self.repo.get_companies_by_user_identifier(self.user.email)
        assert results == []

    def test_get_companies_by_user_identifier_when_success(self):
        self.session.add(self.user)
        self.session.add(self.company)
        company2 = Company(name='Second Corp', short_name='second')
        self.session.add(company2)
        self.session.commit()

        # Add relations
        self.session.execute(
            user_company.insert().values([
                {'user_id': self.user.id, 'company_id': self.company.id, 'role': 'owner'},
                {'user_id': self.user.id, 'company_id': company2.id, 'role': 'member'}
            ])
        )
        self.session.commit()

        # Act
        results = self.repo.get_companies_by_user_identifier(self.user.email)

        # Assert
        assert len(results) == 2

        # Mapping results for easier assertion irrespective of order
        # Result format is [(CompanyObj, 'role_str'), ...]
        result_map = {comp.short_name: role for comp, role in results}

        assert result_map['open'] == 'owner'
        assert result_map['second'] == 'member'

    def test_get_companies_by_user_identifier_when_user_does_not_exist(self):
        results = self.repo.get_companies_by_user_identifier("nonexistent@mail.com")
        assert results == []

    def test_create_company_when_company_exists(self):
        self.session.add(self.company)
        self.session.commit()

        result = self.repo.create_company(Company(short_name='open'))

        assert result.id == self.company.id
        assert result.name == self.company.name

    def test_create_company_when_new_company(self):
        result = self.repo.create_company(Company(name='NewCompany', short_name='new'))

        assert result.id is not None
        assert result.name == 'NewCompany'

    def test_get_user_role_in_company_when_relation_exists(self):
        # arrange
        self.session.add(self.user)
        self.session.add(self.company)
        self.session.commit()

        # insertar relación en la tabla de asociación con rol "admin"
        self.session.execute(
            user_company.insert().values(
                user_id=self.user.id,
                company_id=self.company.id,
                role='admin'
            )
        )
        self.session.commit()

    def test_get_company_users_with_details(self):
        # Arrange: Setup users, company, relation and access logs
        self.session.add(self.user)
        self.session.add(self.company)
        self.session.commit()

        # Add user-company relation with role
        self.session.execute(
            user_company.insert().values(
                user_id=self.user.id,
                company_id=self.company.id,
                role='admin'
            )
        )

        # Add access log
        log_time = datetime(2024, 1, 1, 12, 0, 0)
        log = AccessLog(
            id=1,
            company_short_name=self.company.short_name,
            user_identifier=self.user.email,
            auth_type='local',
            outcome='success',
            source_ip='127.0.0.1',
            request_path='/login',
            timestamp=log_time
        )
        self.session.add(log)
        self.session.commit()

        # Act
        results = self.repo.get_company_users_with_details(self.company.short_name)

        # Assert
        assert len(results) == 1
        user_obj, role, last_access = results[0]

        assert user_obj.email == self.user.email
        assert role == 'admin'
        assert last_access == log_time

    def test_get_user_role_in_company_when_no_relation(self):
        # arrange
        self.session.add(self.user)
        self.session.add(self.company)
        self.session.commit()
        role = self.repo.get_user_role_in_company(self.user.id, self.company.id)

        assert role is None

    def test_save_feedback_when_ok(self):
        company = self.repo.create_company(Company(name='my_company', short_name='my_company'))
        feedback = UserFeedback(company_id=company.id,
                                user_identifier='flibe',
                                message='feedback message',
                                rating=4)
        new_feed = self.repo.save_feedback(feedback)
        assert new_feed.message == 'feedback message'
        assert new_feed.rating == 4

    def test_get_company_by_short_name_retries_once_on_operational_error(self):
        mock_db_manager = MagicMock()
        mock_session = MagicMock()
        mock_db_manager.get_session.return_value = mock_session

        repo = ProfileRepo(mock_db_manager)
        expected_company = Company(name='retry_company', short_name='retry')

        query_chain = mock_session.query.return_value.filter.return_value
        query_chain.first.side_effect = [
            OperationalError("SELECT 1", {}, Exception("ssl eof")),
            expected_company,
        ]

        result = repo.get_company_by_short_name('retry')

        assert result == expected_company
        assert query_chain.first.call_count == 2
        mock_db_manager.remove_session.assert_called_once()
