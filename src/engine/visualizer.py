import plotly.express as px
import pandas as pd
import uuid

def generate_plot(df: pd.DataFrame) -> str:
    """
    Generate Plotly chart from a DataFrame (auto-detects chart type).
    """
    if df.shape[1] < 2:
        return ""

    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    if len(numeric_cols) >= 2:
        fig = px.line(df, x=numeric_cols[0], y=numeric_cols[1])
    elif len(numeric_cols) == 1:
        fig = px.histogram(df, x=numeric_cols[0])
    else:
        fig = px.bar(df, x=df.columns[0], y=df.columns[1])

    fig.update_layout(title="Auto-Generated Chart", height=400)
    div_id = f"plotly-chart-{uuid.uuid4().hex}"
    return fig.to_html(full_html=False, include_plotlyjs='cdn', div_id=div_id)