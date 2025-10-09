## Copyright (c) 2024 Fernando Libedinsky

from dotenv import load_dotenv
from iatoolkit import IAToolkit, register_company
from companies.sample_company.sample_company import SampleCompany
from urllib.parse import urlparse
import os
import logging

# load environment variables
load_dotenv()

def create_app():
    # IMPORTANT: companies must be registered before creating the IAToolkit
    register_company('sample_company', SampleCompany)

    # create the IAToolkit and Flask instance
    toolkit = IAToolkit()
    return toolkit.create_iatoolkit()


if __name__ == "__main__":
    app = create_app()
    if app:
        base_url = os.getenv('IATOOLKIT_BASE_URL')
        run_port = 5001
        if base_url:
            try:
                parsed_url = urlparse(base_url)
                if parsed_url.port:
                    run_port = parsed_url.port
                else:
                    logging.warning(f"IATOOLKIT_BASE_URL ('{base_url}') has no port. Using default {run_port}.")
            except Exception as e:
                logging.error(f"Failed to parse IATOOLKIT_BASE_URL: '{base_url}'. Error: {e}. Using default {run_port}.")
        else:
            logging.info(f"IATOOLKIT_BASE_URL not set. Using default {run_port}.")
        app.run(port=run_port)