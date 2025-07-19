# ScalAble — A Natural Language to SQL/NoSQL interface for Your Databases

**ScalAble** is a lightweight, extensible, and user-friendly web application that allows users to interact with their SQL and NoSQL databases using **natural language queries**. Whether you're a developer, analyst, or data scientist, ScalAble bridges the gap between human intent and complex database query logic using LLMs — all while keeping your data private and under your control.

---

## Features

- **Multi-Database Support**:
  - PostgreSQL
  - MySQL
  - Microsoft SQL Server
  - MongoDB

- **Natural Language Querying**:
  - Write simple English instructions.
  - Get optimized SQL/MongoDB queries generated automatically.
  - Powered by locally hosted LLMs (via Ollama, etc.).

- **Smart Metadata Extraction**:
  - Automatic schema inspection, key detection, row/sample stats.
  - Normalization guess, column data types, size and usage.

- **Guest and Authenticated Modes**:
  - Guest users can connect temporarily.
  - Logged-in users get persistent access to saved databases and chat history (via PostgreSQL backend).

- **Visual Results**:
  - Tabular display of query outputs.
  - Plotly-based visualizations (line, bar, pie, etc.).

- **Modular Connectors**:
  - Easily extend to more databases or APIs with a plug-and-play architecture.

---

- **Ideas so far**:
  - Database intercommunication
  - Data Visualization
  - One prompt for multiple databases
  - Centralized interface to run user's queries without LLM on their desired database

## Setup Instructions

---

## UI Preview

| Add Database | Ask a Query | Generated SQL |
|--------------|-------------|----------------|
| ![Add DB](./screenshots/add_db.png) | ![Query](./screenshots/query.png) | ![Output](./screenshots/output.png) |

---

### 1. Clone the Repository

```bash
git clone https://github.com/ansh2903/scalable.git
cd scalable