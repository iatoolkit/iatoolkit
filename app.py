# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import os
import sys

# Add src/ to sys.path BEFORE importing iatoolkit
# this is only needed when iatoolkit is running without importing the pip package
src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
sys.path.insert(0, src_path)

from dotenv import load_dotenv
from iatoolkit.core import IAToolkit
from iatoolkit.company_registry import register_company
from companies.ent_company.ent_company import EntCompany

# load environment variables
load_dotenv(override=True)

def create_app():
    # IMPORTANT: companies must be registered before creating the IAToolkit
    register_company('ent_company', EntCompany)


    # create the IAToolkit and Flask instance
    toolkit = IAToolkit()
    return toolkit.create_iatoolkit()


app = create_app()

if __name__ == "__main__":
    if app:
        app.run(debug=True)