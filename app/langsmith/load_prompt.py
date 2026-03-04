# app/langsmith/load_prompt.py

import os
from langsmith import Client
from langchain_core.prompts import PromptTemplate

def load_prompt_from_langsmith(prompt_name: str):
    """
    Load a prompt template directly from LangSmith Prompt Hub using the LangSmith Client.
    Falls back to a local default prompt if loading fails.
    """
    try:
        LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
        if not LANGSMITH_API_KEY:
            raise EnvironmentError("Missing LANGSMITH_API_KEY in environment variables.")

        # Initialize LangSmith client
        client = Client(api_key=LANGSMITH_API_KEY)

        # Pull the prompt from LangSmith
        prompt = client.pull_prompt(prompt_name, include_model=False)

        if not prompt:
            raise ValueError("LangSmith returned empty or invalid prompt.")

        print(f"✅ Successfully loaded prompt '{prompt_name}' from LangSmith.")
        return prompt

    except Exception as e:
        print(f"❌ Error loading prompt '{prompt_name}': {e}")
        print("⚠️ Using fallback prompt instead.")

        # Fallback prompt template
        fallback = PromptTemplate.from_template(
            "You are a helpful document generator. Clean and organize the following PM data:\n\n{sections}"
        )
        return fallback
