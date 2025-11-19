## Copyright (c) 2024 Fernando Libedinsky

from dotenv import load_dotenv
from iatoolkit.iatoolkit import IAToolkit
from iatoolkit.company_registry import register_company
from companies.sample_company.sample_company import SampleCompany
from urllib.parse import urlparse
import os
import logging
import sys

src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
sys.path.insert(0, src_path)

# load environment variables
load_dotenv()

def create_app():
    # IMPORTANT: companies must be registered before creating the IAToolkit
    register_company('sample_company', SampleCompany)

    # create the IAToolkit and Flask instance
    toolkit = IAToolkit()
    return toolkit.create_iatoolkit()


app = create_app()

if __name__ == "__main__":
    if app:
        default_port = 5007
        app.run(debug=True, port=default_port)