'''
This module is responsible for providing various visualization methods
to visualize the data in the database and the results of the queries
'''

import plotly
from flask import session

def csv(raw_data):
    # Get the last query results from session
    query_results = raw_data.get('query_results')
    
    if not query_results:
        return True, "No query results available for visualization."
    
    html_data = query_results.get('html_data')
    if not html_data:
        return True, "No HTML data available for visualization."

    # Convert query results to CSV format for the visualization
    data = query_results.get('data', [])
    data = [list(row) if isinstance(row, tuple) else row for row in data]
    csv_data = ""
    
    for row in data:
        csv_data += ",".join(map(str, row)) + "\n"
    
    return csv_data

def analyse_query_results():
    """
    Analyse the last query results stored in session.
    Returns a dictionary with processed data that can be used anywhere (e.g., chat).
    """
    query_results = session.get('last_query_results')

    if not query_results:
        return {"no_data": True}

    db_type = query_results.get('db_type', "")
    html_data = query_results.get('html_data')

    if not html_data:
        return {"no_data": True}

    data = query_results.get('data', [])
    data = [list(row) if isinstance(row, tuple) else row for row in data]

    return {
        "no_data": False,
        "db_type": db_type,
        "html_data": html_data,
        "data": data
    }
