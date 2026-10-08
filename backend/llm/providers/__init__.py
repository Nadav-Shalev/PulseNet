"""The LLM providers. LLMService depends only on the Provider interface; which
provider runs is picked by LLM_PROVIDER in ../config.py."""

from .base import Provider
from .course import CourseProvider
from .fake import FakeProvider
from .openai_compat import OpenAICompatProvider

__all__ = ["Provider", "FakeProvider", "OpenAICompatProvider", "CourseProvider"]
