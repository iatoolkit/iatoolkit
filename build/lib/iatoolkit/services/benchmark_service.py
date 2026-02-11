# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pandas as pd
import time
import logging
from injector import inject
from iatoolkit.services.query_service import QueryService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.common.exceptions import IAToolkitException


class BenchmarkService:
    @inject
    def __init__(self, query_service: QueryService, profile_repo: ProfileRepo):
        self.query_service = query_service
        self.profile_repo = profile_repo

    def _update_results_row(self, df: pd.DataFrame, index: int,
                            status: str,
                            context_time: float,
                            gpt_time: float,
                            answer: str,
                            error_msg: str,
                            query_id: int,
                            stats: dict):
        df.at[index, 'status'] = status
        df.at[index, 'context_time'] = round(context_time, 2)
        df.at[index, 'gpt_time'] = round(gpt_time, 2)
        df.at[index, 'answer'] = answer
        df.at[index, 'error_message'] = error_msg[:512]
        df.at[index, 'query_id'] = query_id
        df.at[index, 'in_tokens'] = stats.get('input_tokens', 0)
        df.at[index, 'out_tokens'] = stats.get('output_tokens', 0)
        df.at[index, 'retry'] = stats.get('sql_retry_count', 0)

    def run(self, company_short_name: str, file_path: str):
        if not file_path.endswith('.xlsx'):
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER,
                        f"solo se leer archivos .xlsx")

        try:
            df = pd.read_excel(file_path, keep_default_na=False)
        except FileNotFoundError:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME,
                        f"El archivo no fue encontrado en: {file_path}")

        required_columns = ['username', 'client_identity', 'prompt_name', 'question', 'model']
        if not all(col in df.columns for col in required_columns):
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER,
                               f"La planilla debe contener las columnas: {required_columns}")

        # Añadir columnas para los resultados
        df['status'] = 'pending'
        df['context_time'] = 0.0
        df['gpt_time'] = 0.0
        df['answer'] = ''
        df['error_message'] = ''
        df['query_id'] = 0
        df['in_tokens'] = 0
        df['out_tokens'] = 0
        df['retry'] = 0

        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.CONFIG_ERROR, f"Compañía {company_short_name} no encontrada.")

        total_rows = len(df)
        logging.info(f"Iniciando benchmark para {total_rows} casos de prueba desde el archivo: {file_path}")

        for index, row in df.iterrows():
            status = 'OK'
            error_msg = ''
            answer = ''
            stats = {}

            try:
                username = str(row['username'])
                client_identity = str(row['client_identity'])
                prompt_name = str(row['prompt_name'])
                question = str(row['question'])
                model = str(row['model'])

                logging.info(
                    f"*** Procesando caso {index + 1}/{total_rows}: client_rut='{client_identity}', prompt='{prompt_name}'")

                # 1. init context with user executing the test
                start_time = time.time()
                self.query_service.llm_init_context(company.short_name,
                                                    external_user_id=username,
                                                    model=model)
                context_time = time.time() - start_time

                # 2. prepare client data.
                client_data = {'client_identity': client_identity}

                # 3. execute the query
                start_time = time.time()
                response = self.query_service.llm_query(
                    company_short_name=company.short_name,
                    prompt_name=prompt_name,
                    question=question,
                    external_user_id=username,
                    client_data=client_data
                )
                gpt_time = time.time() - start_time

                # 4. process the response
                if response.get('error') or not response.get('valid_response'):
                    status = 'FAILED'
                    error_msg = response.get('error_message', 'Error desconocido en la respuesta.')
                else:
                    answer = response.get('answer', '')
                    stats = response.get('stats', {})

                query_id = response.get('query_id', 0)

            except Exception as e:
                status = 'FAILED'
                error_msg = f"Excepción durante la ejecución: {type(e).__name__} - {str(e)}"
                logging.error(f"Fallo en el caso {index + 1}: {error_msg}")

            finally:
                self._update_results_row(df, index,
                                         status=status,
                                         context_time=context_time,
                                         gpt_time=gpt_time,
                                         answer=answer,
                                         error_msg=error_msg,
                                         stats=stats,
                                         query_id=query_id)

        output_filename = file_path.replace('.xlsx', '_results.xlsx')
        df.to_excel(output_filename, index=False)
        logging.info(f"Benchmark finalizado. Resultados guardados en: {output_filename}")

        return output_filename