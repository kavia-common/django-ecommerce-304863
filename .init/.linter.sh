source venv/bin/activate && ruff check . && pylint --ignore=migrations --rcfile .pylintrc core djecommerce combined_wsgi.py manage.py
