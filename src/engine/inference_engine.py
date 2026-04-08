import os

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_message_histories import ChatMessageHistory

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

import dotenv
import time
from src.core.logger import logging
from src.core.exception import CustomException
from src.core.utils import load_settings

dotenv.load_dotenv()

class InferenceEngine:
    def __init__(self, provider, model_name):
        self.provider = provider.lower()
        self.model_name = model_name
        self.history = ChatMessageHistory()
        self.llm = self._initialize_llm()

    def _initialize_llm(self):
        settings = load_settings()

        # Ollama
        if self.provider == "ollama":
            try:
                logging.info(f"Initializing Ollama LLM with model: {self.model_name}")
                return ChatOllama(
                    model = self.model_name,
                    base_url = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434"),
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
                    api_key=os.getenv("OPENAI_API_KEY"),
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
                    api_key=os.getenv("ANTHROPIC_API_KEY"),
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
                    google_api_key=os.getenv("GOOGLE_API_KEY"),
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
                    base_url=os.getenv("LMSTUDIO_BASE") + "/v1",
                    api_key="not-needed",
                    temperature=settings["options"].get("temperature", 0.7),
                    max_tokens=settings["options"].get("num_predict", 256),
                    top_p=settings["options"].get("top_p", 0.9),
                )
            except Exception as e:
                logging.error(f"Error initializing LM Studio LLM: {str(e)}")
                raise e
        else:
            raise ValueError(f"Provider {self.provider} not supported.")

    def get_query_prompt(self):
        """Returns the structured system prompt for XML generation."""
        
        system_instructions = """You are a professional {db_type} query generation expert. 
        Convert natural language into executable {db_type} queries and behave like a friendly assistant.

        DATABASE METADATA:
        {metadata}

        STRICT OUTPUT RULES:
        1. Return output using ONLY these XML tags: <query> and <comment>.
        2. <query>: Valid, executable {db_type} query string. No markdown, no backticks.
        3. <comment>: Markdown-formatted explanation or friendly reply.
        4. Do NOT include any text outside these tags.

        Example:
        <query>SELECT * FROM users;</query><comment>I've fetched all users for you.</comment>"""

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
                print(token)
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
