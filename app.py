## Copyright (c) 2024 Fernando Libedinsky
import os
import sys

# Add src/ to sys.path BEFORE importing iatoolkit
# this is only needed when iatoolkit is running without importing the pip package
src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
sys.path.insert(0, src_path)

from dotenv import load_dotenv
from iatoolkit.iatoolkit import IAToolkit
from iatoolkit.company_registry import register_company
from companies.sample_company.sample_company import SampleCompany

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
        app.run(debug=True)