'''
This module is responsible for providing various visualization methods
to visualize the data in the database and the results of the queries
'''

import plotly

def render_result_table(result):
    if not result:
        return "<p>No results found.</p>"

    # If result is list of dicts (e.g., from Mongo or SQLAlchemy)
    # Updated check
    if isinstance(result[0], (list, tuple)):
        headers = result[0]
        rows = result[1:]
  # If result is list of tuples with column info
    elif isinstance(result[0], (list, tuple)):
        headers = [f"Column {i+1}" for i in range(len(result[0]))]
        rows = result
    else:
        return "<p>Unknown result format.</p>"

    table_html = "<table class='table table-bordered table-sm table-hover table-striped'>"
    # Header row
    table_html += "<thead class='thead-dark'><tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr></thead>"
    # Data rows
    table_html += "<tbody>"
    for row in rows:
        table_html += "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
    table_html += "</tbody></table>"

    return table_html
