import json
import os

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import StructuredTool
from langchain_community.chat_message_histories import ChatMessageHistory

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

import dotenv
import time
from spore._logger import logging
from spore._exception import CustomException
from spore._utils import load_settings, provider_base_url
from spore._engine.tools import parse_xml_tool_response, tool_schemas

dotenv.load_dotenv()

class InferenceEngine:
    def __init__(self, provider, model_name):
        self.provider = provider.lower()
        self.model_name = model_name
        self.history = ChatMessageHistory()
        self.llm = self._initialize_llm()

    def _initialize_llm(self):
        settings = load_settings()

        def _api_key(provider: str, env_var: str, default: str = "") -> str:
            keys = settings.get("api_keys") or {}
            return keys.get(provider) or os.getenv(env_var) or default

        # Ollama
        if self.provider == "ollama":
            try:
                logging.info(f"Initializing Ollama LLM with model: {self.model_name}")
                return ChatOllama(
                    model = self.model_name,
                    base_url = provider_base_url("ollama", settings),
                    reasoning = False,
                    keep_alive = settings.get("keep_alive", "5m"),  # how long to keep model in VRAM
                    num_predict = settings["options"].get("num_predict", 256),  # max tokens to generate
                    num_ctx = settings["options"].get("num_ctx", 2048),         # context window size
                    num_batch = settings["options"].get("num_batch", 4),        # batch size for prompt processing
                    num_thread = settings["options"].get("num_thread", 8),      # CPU threads
                    num_gpu = settings["options"].get("num_gpu", 0),            # GPU layers to offload
                    top_k = settings["options"].get("top_k", 40),               # limits vocabulary to top K tokens
                    top_p = settings["options"].get("top_p", 0.9),              # nucleus sampling threshold
                    temperature = settings["options"].get("temperature", 0.7),  # randomness
                    repeat_penalty = settings["options"].get("repeat_penalty", 1.1),
                    use_mmap = settings["options"].get("use_mmap", True),       # memory-map model file
                    use_mlock = settings["options"].get("use_mlock", False),    # lock model in RAM, prevents swapping
                )
            except Exception as e:
                logging.error(f"Error initializing Ollama LLM: {str(e)}")
                raise e

        # OpenAI
        elif self.provider == "openai":
            try:
                logging.info(f"Initializing OpenAI LLM with model: {self.model_name}")
                return ChatOpenAI(
                    model=self.model_name,
                    api_key=_api_key("openai", "OPENAI_API_KEY"),
                    base_url=provider_base_url("openai", settings),
                    temperature=settings["options"].get("temperature", 0.7),
                    max_tokens=settings["options"].get("num_predict", 256),
                    top_p=settings["options"].get("top_p", 0.9),
                    frequency_penalty=0.0,
                    presence_penalty=0.0,
                )
            except Exception as e:
                logging.error(f"Error initializing OpenAI LLM: {str(e)}")
                raise e

        # Anthropic
        elif self.provider == "anthropic":
            try:
                return ChatAnthropic(
                    model=self.model_name,  # claude-3-5-sonnet-20241022, etc.
                    api_key=_api_key("anthropic", "ANTHROPIC_API_KEY"),
                    temperature=settings["options"].get("temperature", 0.7),
                    max_tokens=settings["options"].get("num_predict", 256),
                    top_p=settings["options"].get("top_p", 0.9),
                    top_k=settings["options"].get("top_k", 40),
                )
            except Exception as e:
                logging.error(f"Error initializing Anthropic LLM: {str(e)}")
                raise e
        
        # Google Gemini
        elif self.provider == "gemini":
            try:
                return ChatGoogleGenerativeAI(
                    model=self.model_name,  # gemini-1.5-pro, gemini-1.5-flash
                    google_api_key=_api_key("gemini", "GOOGLE_API_KEY"),
                    temperature=settings["options"].get("temperature", 0.7),
                    max_output_tokens=settings["options"].get("num_predict", 256),
                    top_p=settings["options"].get("top_p", 0.9),
                    top_k=settings["options"].get("top_k", 40),
                )
            except Exception as e:
                logging.error(f"Error initializing Google Gemini LLM: {str(e)}")
                raise e

        # LM Studio (OpenAI-compatible)
        elif self.provider == "lmstudio":
            try:
                return ChatOpenAI(
                    model=self.model_name,
                    base_url=provider_base_url("lmstudio", settings) + "/v1",
                    api_key=_api_key("lmstudio", "LMSTUDIO_API_KEY", "not-needed"),
                    temperature=settings["options"].get("temperature", 0.7),
                    max_tokens=settings["options"].get("num_predict", 256),
                    top_p=settings["options"].get("top_p", 0.9),
                )
            except Exception as e:
                logging.error(f"Error initializing LM Studio LLM: {str(e)}")
                raise e
        else:
            raise ValueError(f"Provider {self.provider} not supported.")

    def supports_native_tools(self) -> bool:
        return self.provider in ("openai", "anthropic", "gemini")

    def get_agent_system_prompt(self) -> str:
        return """You are ScalAble Workspace Agent — a local-first data analysis assistant.

EXECUTION POLICY (strict):
- You may EXECUTE tools only on LOCAL materialized relations (catalog @refs), notebook Python, and dashboard widgets.
- For REMOTE data sources you may ONLY use propose_sql to generate SQL. The human executes SQL in the Data panel.
- NEVER attempt to run SQL against remote databases directly.

WORKSPACE CONTEXT:
{system_context}

AVAILABLE TOOLS (exact names only — do NOT invent names):
- propose_sql — args: {{"question": "...", "source_id": "optional"}}
- describe_relation — args: {{"ref": "<relation_ref_from_context>"}}
- query_relation — args: {{"ref": "<relation_ref_from_context>", "transform": {{}}, "limit": 100}}
- render_chart — args: {{"ref": "<relation_ref_from_context>", "chart_type": "bar|line|pie", "x_field": "...", "y_field": "..."}}
- run_python — args: {{"code": "..."}}
- add_notebook_cell — args: {{"type": "python", "code": "..."}}
- add_dashboard_widget — args: {{"type": "bar", "ref": "<relation_ref_from_context>", "title": "..."}}

Full JSON schemas:
{tool_schemas}

OUTPUT PROTOCOL — use EXACTLY ONE of these per response:

Example tool call (replace placeholder with a real ref from context.relations):
<thought>Inspect the local relation schema first.</thought>
<tool name="describe_relation">{{"ref": "<relation_ref_from_context>"}}</tool>

Example chart after querying:
<thought>Build a bar chart of counts by category.</thought>
<tool name="render_chart">{{"ref": "<relation_ref_from_context>", "chart_type": "bar", "x_field": "category", "y_field": "count"}}</tool>

Example conversational reply (greetings, general questions, unclear requests):
<thought>User sent a greeting.</thought>
<final><comment>Hello! I can help analyze local @relations, run notebook code, or propose SQL for your connected sources. What would you like to do?</comment></final>

Example final answer (no more tools):
<thought>Analysis complete.</thought>
<final><comment>Here is a summary of the findings…</comment></final>

Rules:
- Replace ALL placeholders (e.g. <relation_ref_from_context>) with real values from WORKSPACE CONTEXT. Never use a literal placeholder or example value.
- context.relations lists every queryable file on the workspace volume (streams and datasets). Use refs exactly as listed.
- Only call describe_relation, query_relation, or render_chart for refs that appear in context.relations.
- If context.relations is empty, respond with <final><comment>…</comment></final> and DO NOT call relation tools. Offer to propose SQL or explain how to materialize data.
- For greetings, small talk, or requests that do not need data tools, respond directly with <final><comment>…</comment></final> without calling tools.
- When the user asks to plot/chart/graph/visualize data, you MUST call render_chart with a real ref from context.relations. NEVER describe a chart in <final> text without calling the tool first.
- When the user asks to analyze in the notebook, call add_notebook_cell or run_python — do not only describe notebook steps in text.
- When the user asks for a dashboard widget or visualization on the dashboard, call add_dashboard_widget with a real ref — do not only describe widgets in text.
- Local models: prefer one simple tool call per step. Call describe_relation before render_chart if you are unsure of column names.
- NEVER output the literal text TOOL_NAME — always use a real tool name from the list above.
- One tool per step unless finishing with <final>.
- Tool args must be valid JSON inside <tool> tags (use double quotes for keys and strings).
- For charts on local data use describe_relation then render_chart (or render_chart directly if columns are known).
- Prefer local @relations from WORKSPACE CONTEXT over remote sources.
- Use relation refs exactly as listed in context.relations.
"""

    def get_query_prompt(self):
        system_instructions = """You are a professional {db_type} query generation expert who is thorough with everything. 
        Convert natural language into executable {db_type} queries and behave like a friendly assistant.

        DATABASE METADATA:
        {metadata}

        STRICT OUTPUT RULES:
        1. Return output using ONLY these XML tags: <query> and <comment>.
        2. <query>: Valid, executable {db_type} query string. If no query is needed, leave this tag empty: <query></query>.
        3. <comment>: Markdown-formatted explanation or friendly reply.
        4. Do NOT include any text outside these tags.
        5. Push all filters, joins, aggregations, and sampling into SQL (WHERE, GROUP BY, TABLESAMPLE, LIMIT).
        6. Never suggest pandas, pd.read_sql, or pulling full tables into Python — SQL runs on the remote source.

        EXAMPLES:
        User: "hello"
        Assistant: <query></query><comment>Hello! I'm ready to help you query your {db_type} database. What are we looking for today?</comment>

        User: "show me all users"
        Assistant: <query>SELECT * FROM users;</query><comment>I've retrieved all records from the users table for you.</comment>

        User: "clear the history"
        Assistant: <query></query><comment>I can't physically clear the UI, but I'm ready for your next fresh request!</comment>"""
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_instructions),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{input}"),
        ])  

        return prompt        

    def generate(self, user_input, db_type, metadata):
        """Executes the inference and returns structured data."""
        logging.info(f"Generating inference via {self.provider} ({self.model_name})")

        if len(self.history.messages) > 20:
            self.history.messages = self.history.messages[-20:]

        system_prompt = self.get_query_prompt()

        chain = system_prompt | self.llm

        start_time = time.time()
        token_count = 0        
        full_response = ""
        for chunk in chain.stream({
            "input": user_input,
            "history": self.history.messages,
            "db_type": db_type,
            "metadata": metadata
            }):
                token = chunk.content
                token_count += 1
                full_response += token
                yield {
                    "type": "token",
                    "content": token
                }
        
        elapsed = time.time() - start_time

        self.history.add_user_message(user_input)
        self.history.add_ai_message(full_response)

        yield {
            "type": "stats",
            "tokens_generated": token_count,
            "time_seconds": round(elapsed, 2),
            "tokens_per_second": round(token_count / elapsed, 1) if elapsed > 0 else token_count
        }

    # Small conversational prompt for greetings / general replies. Deliberately
    # tiny (no tool protocol, no JSON schemas) to keep the context window small
    # for local models. {context} is a value slot, so user/data braces are safe.
    CONVERSE_SYSTEM = (
        "You are ScalAble, a local-first data analysis assistant. "
        "Be concise, friendly, and honest. Do NOT invent data, results, or column values.\n\n"
        "Workspace summary (JSON):\n{context}\n\n"
        "Users can reference a dataset with @name and ask for a chart, a table, or a SQL "
        "proposal for a connected source. If there are no relations, suggest connecting a "
        "source or uploading data. Keep replies to a few sentences."
    )

    def converse(self, user_msg: str, context_summary, history=None):
        """Stream a short conversational reply (no tools, minimal context)."""
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.CONVERSE_SYSTEM),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{input}"),
        ])
        chain = prompt | self.llm
        ctx_text = (
            context_summary
            if isinstance(context_summary, str)
            else json.dumps(context_summary, default=str)
        )
        for chunk in chain.stream({
            "input": (user_msg or "").strip() or "(no message)",
            "history": history or [],
            "context": ctx_text,
        }):
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            if token:
                yield {"type": "token", "content": token}

    # Human turn template. {latest_message} is filled at render time (its VALUE
    # is inserted literally, so user braces never break templating). Any literal
    # braces in this instruction must be doubled to survive f-string templating.
    _AGENT_HUMAN_TEMPLATE = (
        "The user's latest message is:\n"
        "{latest_message}\n\n"
        "Respond to it now using the OUTPUT PROTOCOL: emit exactly one tool call "
        'as <tool name="NAME">JSON_ARGS</tool>, or finish with '
        "<final><comment>your reply</comment></final>. "
        "If this is a greeting, small talk, or needs no data tools, reply with <final>."
    )

    def agent_step(
        self,
        system_context: str,
        tool_schemas: str,
        history,
        latest_message: str = "",
    ):
        """Single agent iteration — hybrid native tools or XML protocol."""
        if self.supports_native_tools():
            yield from self._agent_step_native(
                system_context, tool_schemas, history, latest_message
            )
        else:
            yield from self._agent_step_xml(
                system_context, tool_schemas, history, latest_message
            )

    def _agent_step_xml(
        self,
        system_context: str,
        tool_schemas: str,
        history,
        latest_message: str = "",
    ):
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.get_agent_system_prompt()),
            MessagesPlaceholder(variable_name="history"),
            ("human", self._AGENT_HUMAN_TEMPLATE),
        ])
        chain = prompt | self.llm
        full_response = ""
        for chunk in chain.stream({
            "system_context": system_context,
            "tool_schemas": tool_schemas,
            "history": history,
            "latest_message": (latest_message or "").strip() or "(no message)",
        }):
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            if token:
                full_response += token
                yield {"type": "token", "content": token}
        parsed = parse_xml_tool_response(full_response)
        yield {"type": "tool_calls", "parsed": parsed, "raw": full_response}

    def _agent_step_native(
        self,
        system_context: str,
        tool_schemas_json: str,
        history,
        latest_message: str = "",
    ):
        """Native tool-calling path; maps tool_calls back to XML-shaped parsed dict."""
        try:
            spec_list = json.loads(tool_schemas_json)
        except (json.JSONDecodeError, TypeError):
            spec_list = tool_schemas()

        def _stub(**kwargs):
            return json.dumps(kwargs)

        lc_tools = []
        for spec in spec_list:
            name = spec["name"]
            lc_tools.append(
                StructuredTool.from_function(
                    func=_stub,
                    name=name,
                    description=spec.get("description", name),
                )
            )

        prompt = ChatPromptTemplate.from_messages([
            ("system", self.get_agent_system_prompt()),
            MessagesPlaceholder(variable_name="history"),
            ("human", self._AGENT_HUMAN_TEMPLATE),
        ])
        llm = self.llm.bind_tools(lc_tools) if lc_tools else self.llm
        chain = prompt | llm

        full_response = ""
        tool_calls_payload = None
        for chunk in chain.stream({
            "system_context": system_context,
            "tool_schemas": tool_schemas_json,
            "history": history,
            "latest_message": (latest_message or "").strip() or "(no message)",
        }):
            token = chunk.content if hasattr(chunk, "content") else ""
            if token:
                full_response += token
                yield {"type": "token", "content": token}
            if hasattr(chunk, "tool_calls") and chunk.tool_calls:
                tool_calls_payload = chunk.tool_calls

        if tool_calls_payload:
            tc = tool_calls_payload[0]
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
            args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
            parsed = {"kind": "tool", "thought": full_response.strip(), "name": name, "args": args or {}}
            yield {"type": "tool_calls", "parsed": parsed, "raw": full_response}
            return

        if full_response.strip():
            parsed = parse_xml_tool_response(full_response)
            if parsed.get("kind") == "text":
                parsed = {"kind": "final", "comment": full_response.strip(), "thought": ""}
        else:
            parsed = {"kind": "final", "comment": "Done.", "thought": ""}
        yield {"type": "tool_calls", "parsed": parsed, "raw": full_response}
