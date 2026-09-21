"""Build a LangChain ChatOpenAI model from model settings."""

from langchain_openai import ChatOpenAI
from openai import DefaultAsyncHttpxClient, DefaultHttpxClient

from anyagent.configs.agent import ModelSettings


def build_chat_model(
    settings: ModelSettings,
) -> tuple[ChatOpenAI, DefaultAsyncHttpxClient, DefaultHttpxClient]:
    """Create a ChatOpenAI instance and its HTTP clients.

    Returns:
        A tuple of (model, async_client, sync_client). The caller owns
        the clients and must close them on cleanup.
    """
    sync_client = DefaultHttpxClient()
    async_client = DefaultAsyncHttpxClient()
    model = ChatOpenAI(
        model=settings.model,
        base_url=settings.base_url,
        api_key=settings.api_key.get_secret_value(),
        temperature=settings.temperature,
        timeout=settings.timeout_seconds,
        max_retries=settings.max_retries,
        streaming=settings.streaming,
        disable_streaming=not settings.streaming,
        stream_usage=settings.stream_usage,
        use_responses_api=False,
        http_client=sync_client,
        http_async_client=async_client,
    )
    return model, async_client, sync_client
