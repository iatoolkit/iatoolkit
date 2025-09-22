# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit
# Todos los derechos reservados.
# En trámite de registro en el Registro de Propiedad Intelectual de Chile.

from flask.views import MethodView
from flask import render_template, request, redirect, url_for, jsonify
from services.profile_service import ProfileService
from repositories.profile_repo import ProfileRepo
from repositories.llm_query_repo import LLMQueryRepo
from injector import inject
from common.session_manager import SessionManager
from common.auth import IAuthentication


class SelectCompanyView(MethodView):
    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 query_repo: LLMQueryRepo,
                 profile_repo: ProfileRepo,
                 iauthentication: IAuthentication,):
        self.profile_service = profile_service
        self.profile_repo = profile_repo
        self.iauthentication = iauthentication
        self.query_repo = query_repo

    def get(self, company_short_name):
        iaut = self.iauthentication.verify(company_short_name)
        if not iaut.get("success"):
            return jsonify(iaut), 401

        # get company name from url
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html', message="Empresa no encontrada"), 404

        super_user = SessionManager.get('user', {}).get('super_user')
        config_data = self.fill_config_data()  # It's safer to call this here

        # get from session the company user is logged to
        user_agent = request.user_agent
        is_mobile = user_agent.platform in ["android", "iphone", "ipad"] or "mobile" in user_agent.string.lower()
        alert_message = request.args.get('alert_message', None)
        return render_template("select_company.html",
                               companies=config_data,
                               user_company=company_short_name,
                               company=company,
                               company_short_name=company_short_name,
                               alert_message=alert_message,
                               alert_icon='success' if alert_message else None,
                               super_user=super_user,
                               is_mobile=is_mobile)

    def post(self, company_short_name):
        try:
            iaut = self.iauthentication.verify(company_short_name)
            if not iaut.get("success"):
                return jsonify(iaut), 401

            # get company info
            company = self.profile_service.get_company_by_short_name(company_short_name)
            if not company:
                return render_template('error.html', message="Empresa no encontrada"), 404

            # user logged in
            user_id = SessionManager.get('user_id')
            user = self.profile_repo.get_user_by_id(user_id)

            # get company selected by the user
            company_id = request.form.get('company_id')
            selected_company = self.profile_repo.get_company_by_id(int(company_id))

            # update the session
            self.profile_service.set_user_session(user=user, company=selected_company)
            return redirect(url_for('chat',
                                    company=selected_company,
                                    company_short_name=selected_company.short_name,
                                    alert_message='Se actualizo correctamente la empresa'))
        except Exception as e:
            return render_template("error.html",
                                   message="Ha ocurrido un error inesperado."), 500

    def fill_config_data(self):
        companies = []
        company_list = self.profile_service.get_companies()

        for c in company_list:
            self.functions = self.query_repo.get_company_functions(c)
            flist = []
            function_names = []
            for function in self.functions:
                flist.append({'name': function.name, 'description': function.description})
                function_names.append(function.name)

            companies.append(
                {
                    'id': c.id,
                    'name': c.name,
                    'logo_file': c.logo_file,
                    'functions': flist,
                })

        return companies