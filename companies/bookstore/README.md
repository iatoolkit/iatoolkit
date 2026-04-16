
# 📚 Bookstore Example Company

This directory contains a complete, runnable example of a company built with the IAToolkit framework.
It simulates an online bookstore with customers, orders, books, and authors.

## Features Showcased

*   **SQL Data Integration**: Connects to a SQLite database (`bookstore.db`) to answer queries about sales, inventory, and customers.
*   **Document Search (RAG)**: Can be configured to search through store policy documents (using the `onboarding_cards.yaml` and `help_content.yaml` as examples).
*   **Custom Prompts**: Includes specialized prompt templates for "Sales Reports" and "Author Analysis".
*   **Branding**: Fully customized UI with a warm bookstore color theme.

## Quick Start

1.  **Configure Environment**:
    Ensure your `.env` file in the project root includes the following:
    ```bash
    # Use SQLite for the bookstore example
    BOOKSTORE_DATABASE_URI="sqlite:///bookstore.db"
    
    # ... other standard keys (OPENAI_API_KEY, etc.)
    ```

2.  **Initialize the Database**:
    Run the custom CLI command to create the schema and seed sample data:
    ```bash
    flask create-bookstore-db
    ```
    You should see:
    > ✅ Bookstore database ready!

3.  **Run the Application**:
    ```bash
    flask run
    ```

4.  **Access the Bookstore**:
    Open your browser to: [http://127.0.0.1:5000/bookstore/home](http://127.0.0.1:5000/bookstore/home)

## Example Queries to Try

Once registered and logged in:

*   **Sales**: "What were the total sales for 'Science Fiction' books?"
*   **Inventory**: "Which books have low stock?"
*   **Authors**: "Tell me about Isaac Asimov and list his books."
*   **Reporting**: Use the "Sales Report" prompt from the UI.

## Directory Structure

*   `config/`: `company.yaml` (main config), onboarding cards, help content.
*   `context/`: Markdown files describing the business domain.
*   `prompts/`: Jinja2 templates for structured LLM prompts.
*   `schema/`: YAML definitions of the database tables for the LLM.
*   `sample_data/`: SQL scripts for creating and populating the database.
*   `bookstore.py`: The Python class defining the company module.
