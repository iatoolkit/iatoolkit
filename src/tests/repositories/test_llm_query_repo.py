# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import LLMQuery, Function, Company, Prompt, PromptCategory
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from datetime import datetime, timedelta


class TestLLMQueryRepo:
    def setup_method(self):
        self.db_manager = DatabaseManager('sqlite:///:memory:')
        self.db_manager.create_all()
        self.session = self.db_manager.get_session()
        self.repo = LLMQueryRepo(self.db_manager)
        self.query = LLMQuery(id=1, company_id=2,
                              user_identifier='user_1',
                              query="test query",
                              output='an output',
                              response={'answer': 'an answer'},
                              answer_time=3)
        self.function = Function(name="function1",
                                company_id=1,
                                description="A description",
                                parameters={'name': 'value'})
        self.company = Company(name='test_company',
                               short_name='test')
        self.session.add(self.company)
        self.session.commit()


    def test_add_query_when_success(self):
        new_query = self.repo.add_query(self.query)
        assert new_query.id == 1

    def test_get_company_functions_when_ok(self):
        self.function.company_id = self.company.id

        self.session.add(self.function)
        self.session.commit()
        assert len(self.repo.get_company_functions(self.company)) == 1

    def test_create_function_when_new_function(self):
        """Test creating a new function with all fields."""
        new_function = Function(
            name="function1",
            company_id=self.company.id,
            description="A description",
            parameters={'name': 'value'},
            system_function=False
        )
        result = self.repo.create_function(new_function=new_function)
        self.session.commit()  # Commit to persist and check retrieval

        assert result.id is not None
        assert result.name == "function1"
        assert result.description == "A description"
        assert result.parameters == {'name': 'value'}
        assert result.company_id == self.company.id

    def test_create_prompt_when_new_prompt(self):
        """Test creating a new prompt with all fields."""
        new_prompt = Prompt(
            name="prompt1",
            company_id=self.company.id,
            description="an intelligent prompt",
            filename='file.prompt',
            active=True,
            order=5,
            custom_fields=[{'label': 'lbl'}]
        )
        result = self.repo.create_prompt(new_prompt=new_prompt)
        self.session.commit()  # Commit to persist

        assert result.id is not None
        assert result.name == "prompt1"
        assert result.description == "an intelligent prompt"
        assert result.active is True
        assert result.order == 5
        assert result.custom_fields == [{'label': 'lbl'}]

    def test_create_prompt_category(self):
        """Test creating a new prompt category."""
        new_category = PromptCategory(name="Cat1", order=1, company_id=self.company.id)
        result = self.repo.create_prompt_category(new_category)
        self.session.commit()

        assert result.id is not None
        assert result.name == "Cat1"
        assert result.order == 1
        assert result.company_id == self.company.id

    def test_delete_all_functions(self):
        """Test deleting all functions for a specific company."""
        # Create functions for the target company
        f1 = Function(name="f1", company_id=self.company.id, description="d", parameters={})
        f2 = Function(name="f2", company_id=self.company.id, description="d", parameters={})
        self.session.add_all([f1, f2])

        # Create function for another company (should not be deleted)
        other_company = Company(name='other', short_name='other')
        self.session.add(other_company)
        self.session.commit()
        f3 = Function(name="f3", company_id=other_company.id, description="d", parameters={})
        self.session.add(f3)
        self.session.commit()

        assert self.session.query(Function).filter_by(company_id=self.company.id).count() == 2

        self.repo.delete_all_functions(self.company)
        self.session.commit()  # Caller handles commit usually, but here we test the effect

        assert self.session.query(Function).filter_by(company_id=self.company.id).count() == 0
        assert self.session.query(Function).filter_by(company_id=other_company.id).count() == 1

    def test_delete_all_prompts(self):
        """Test deleting all prompts and categories for a specific company."""
        # Setup data for target company
        cat1 = PromptCategory(name="Cat1", order=1, company_id=self.company.id)
        self.session.add(cat1)
        self.session.commit()

        p1 = Prompt(name="p1", company_id=self.company.id, category_id=cat1.id, description="d", filename="f")
        self.session.add(p1)

        # Setup data for another company
        other_company = Company(name='other', short_name='other')
        self.session.add(other_company)
        self.session.commit()

        cat2 = PromptCategory(name="Cat2", order=1, company_id=other_company.id)
        self.session.add(cat2)
        self.session.commit()
        p2 = Prompt(name="p2", company_id=other_company.id, category_id=cat2.id, description="d", filename="f")
        self.session.add(p2)
        self.session.commit()

        assert self.session.query(Prompt).filter_by(company_id=self.company.id).count() == 1
        assert self.session.query(PromptCategory).filter_by(company_id=self.company.id).count() == 1

        self.repo.delete_all_prompts(self.company)
        self.session.commit()

        # Verify target company data is gone
        assert self.session.query(Prompt).filter_by(company_id=self.company.id).count() == 0
        assert self.session.query(PromptCategory).filter_by(company_id=self.company.id).count() == 0

        # Verify other company data remains
        assert self.session.query(Prompt).filter_by(company_id=other_company.id).count() == 1
        assert self.session.query(PromptCategory).filter_by(company_id=other_company.id).count() == 1

    def test_get_history_empty_result(self):
        """Test get_history when no queries exist for the user"""
        # Get history for non-existent user
        history = self.repo.get_history(self.company, 'nonexistent_user')

        # Should return empty list
        assert len(history) == 0
        assert history == []

    def test_get_history_different_company(self):
        """Test get_history filters by company_id correctly"""
        # Add two companies
        company1 = Company(name='company1', short_name='comp1')
        company2 = Company(name='company2', short_name='comp2')
        self.session.add(company1)
        self.session.add(company2)
        self.session.commit()

        # Create queries for different companies
        query1 = LLMQuery(
            company_id=company1.id,
            user_identifier='user123',
            query="Company 1 query",
            output='Company 1 output',
            response={'answer': 'Company 1 answer'},
            answer_time=3
        )
        query2 = LLMQuery(
            company_id=company2.id,
            user_identifier='user123',
            query="Company 2 query",
            output='Company 2 output',
            response={'answer': 'Company 2 answer'},
            answer_time=3
        )

        # Add queries to database
        self.session.add(query1)
        self.session.add(query2)
        self.session.commit()

        # Get history for company1
        history1 = self.repo.get_history(company1, 'user123')
        assert len(history1) == 1
        assert history1[0].query == "Company 1 query"

        # Get history for company2
        history2 = self.repo.get_history(company2, 'user123')
        assert len(history2) == 1
        assert history2[0].query == "Company 2 query"

    def test_get_history_limit_100(self):
        """Test get_history respects the limit of 100 queries"""
        # Create 110 queries
        queries = []
        base_time = datetime(2024, 1, 15, 10, 30, 0)
        for i in range(110):
            # Use timedelta to create unique timestamps
            query = LLMQuery(
                company_id=self.company.id,
                user_identifier='user123',
                query=f"Query {i}",
                output=f'Output {i}',
                response={'answer': f'Answer {i}'},
                answer_time=3,
                created_at=base_time + timedelta(seconds=i)  # Different timestamps
            )
            queries.append(query)

        # Add all queries to database
        for query in queries:
            self.session.add(query)
        self.session.commit()

        # Get history
        history = self.repo.get_history(self.company, 'user123')

        # Should return only 100 queries (limit)
        assert len(history) == 100
        # Should be ordered by created_at desc (newest first)
        assert history[0].query == "Query 109"  # Newest
        assert history[99].query == "Query 10"   # 100th newest

    def test_get_history_mixed_user_types(self):
        """Test get_history correctly filters by user type"""
        # Create queries for different user types
        external_query = LLMQuery(
            company_id=self.company.id,
            user_identifier='external_user',
            query="External user query",
            output='External output',
            response={'answer': 'External answer'},
            answer_time=3
        )
        local_query = LLMQuery(
            company_id=self.company.id,
            user_identifier='user_456',
            query="Local user query",
            output='Local output',
            response={'answer': 'Local answer'},
            answer_time=3
        )

        # Add queries to database
        self.session.add(external_query)
        self.session.add(local_query)
        self.session.commit()

        # Get history for external user
        external_history = self.repo.get_history(self.company, 'external_user')
        assert len(external_history) == 1
        assert external_history[0].query == "External user query"

        # Get history for local user
        local_history = self.repo.get_history(self.company, 'user_456')
        assert len(local_history) == 1
        assert local_history[0].query == "Local user query"

    def test_get_history_ordering(self):
        """Test get_history orders by created_at desc correctly"""

        # Create queries with different timestamps
        old_query = LLMQuery(
            company_id=self.company.id,
            user_identifier='user123',
            query="Old query",
            output='Old output',
            response={'answer': 'Old answer'},
            answer_time=3,
            created_at=datetime(2024, 1, 15, 10, 30, 0)
        )
        new_query = LLMQuery(
            company_id=self.company.id,
            user_identifier='user123',
            query="New query",
            output='New output',
            response={'answer': 'New answer'},
            answer_time=3,
            created_at=datetime(2024, 1, 15, 11, 30, 0)
        )

        # Add queries to database
        self.session.add(old_query)
        self.session.add(new_query)
        self.session.commit()

        # Get history
        history = self.repo.get_history(self.company, 'user123')

        # Should be ordered by created_at desc (newest first)
        assert len(history) == 2
        assert history[0].query == "New query"  # Newest first
        assert history[1].query == "Old query"  # Oldest last

    def test_get_history_no_company_queries(self):
        """Test get_history when company exists but has no queries"""

        # Get history for company with no queries
        history = self.repo.get_history(self.company, 'user123')

        # Should return empty list
        assert len(history) == 0
        assert history == []

    def test_get_prompts_when_prompts_exist(self):
        """Test get_prompts returns all prompts for a company."""
        # Create active and inactive prompts for the same company
        prompt1 = Prompt(name="active_prompt",
                         company_id=self.company.id,
                         description="An active prompt",
                         active=True,
                         filename='')
        prompt2 = Prompt(name="inactive_prompt",
                         company_id=self.company.id,
                         description="An inactive prompt",
                         active=False,
                         filename='')

        self.session.add_all([prompt1, prompt2])
        self.session.commit()

        # Get prompts for the company
        prompts = self.repo.get_prompts(self.company)

        # Should return both prompts
        assert len(prompts) == 2
        prompt_names = {p.name for p in prompts}
        assert "active_prompt" in prompt_names
        assert "inactive_prompt" in prompt_names

    def test_get_prompts_when_no_prompts_exist(self):
        """Test get_prompts returns an empty list when a company has no prompts."""
        # Get prompts for a company with no prompts
        prompts = self.repo.get_prompts(self.company)

        # Should return an empty list
        assert len(prompts) == 0
        assert prompts == []

    def test_get_prompts_filters_by_company(self):
        """Test get_prompts only returns prompts for the specified company."""
        # Create another company
        other_company = Company(name='other_company', short_name='other')
        self.session.add(other_company)
        self.session.commit()

        # Create a prompt for the main company
        prompt1 = Prompt(name="main_company_prompt",
                         company_id=self.company.id,
                         description="Prompt for the main company",
                         filename='')

        # Create a prompt for the other company
        prompt2 = Prompt(name="other_company_prompt",
                         company_id=other_company.id,
                         description="Prompt for the other company",
                         filename='')

        self.session.add_all([prompt1, prompt2])
        self.session.commit()

        # Get prompts for the main company
        prompts = self.repo.get_prompts(self.company)

        # Should only return the prompt for the main company
        assert len(prompts) == 1
        assert prompts[0].name == "main_company_prompt"
        assert prompts[0].company_id == self.company.id

    # ... existing code ...
    def test_get_system_prompts(self):
        """Test get_system_prompts filters correctly."""
        # Create regular prompt
        p1 = Prompt(name="regular", company_id=self.company.id, description="d", filename="f", is_system_prompt=False)

        # Create system prompt (active)
        sp1 = Prompt(name="sys1", description="sys desc", filename="f", is_system_prompt=True, active=True, order=2)

        # Create system prompt (inactive)
        sp2 = Prompt(name="sys2", description="sys desc", filename="f", is_system_prompt=True, active=False, order=1)

        # Create system prompt (active, order 1)
        sp3 = Prompt(name="sys3", description="sys desc", filename="f", is_system_prompt=True, active=True, order=1)

        self.session.add_all([p1, sp1, sp2, sp3])
        self.session.commit()

        results = self.repo.get_system_prompts()

        # Should return only active system prompts, ordered by 'order'
        assert len(results) == 2
        assert results[0].name == "sys3"  # order 1
        assert results[1].name == "sys1"  # order 2

    def test_get_prompt_by_name(self):
        """Test get_prompt_by_name returns the correct prompt."""
        p1 = Prompt(name="target_prompt", company_id=self.company.id, description="d", filename="f")
        p2 = Prompt(name="other_prompt", company_id=self.company.id, description="d", filename="f")

        # Prompt for another company with same name
        other_company = Company(name='other', short_name='other')
        self.session.add(other_company)
        self.session.commit()
        p3 = Prompt(name="target_prompt", company_id=other_company.id, description="d", filename="f")

        self.session.add_all([p1, p2, p3])
        self.session.commit()

        # Should find the prompt for the correct company
        result = self.repo.get_prompt_by_name(self.company, "target_prompt")
        assert result is not None
        assert result.id == p1.id
        assert result.company_id == self.company.id

        # Should return None if prompt doesn't exist for that company
        result_none = self.repo.get_prompt_by_name(self.company, "non_existent")
        assert result_none is None
