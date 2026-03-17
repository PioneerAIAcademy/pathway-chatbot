import logging
import os
from typing import List

from app.api.routers.models import Message
from langfuse.decorators import langfuse_context, observe
from llama_index.core.prompts import PromptTemplate
from llama_index.core.settings import Settings
from pydantic import BaseModel

NEXT_QUESTIONS_SUGGESTION_PROMPT = PromptTemplate(
    "You are a helpful assistant for BYU-Pathway Worldwide missionaries. "
    "Your task is to suggest the next question that the user might ask. "
    "IMPORTANT: Never use second-person pronouns (you, your, yours). "
    "Instead, use impersonal phrasing like 'students', 'missionaries', or general language. "
    "For example, say 'What are the registration deadlines?' instead of 'When do you need to register?'."
    "\nHere is the conversation history"
    "\n---------------------\n{conversation}\n---------------------"
    "Given the conversation history, please give {number_of_questions} questions that might be asked next!"
)
N_QUESTION_TO_GENERATE = 3


logger = logging.getLogger("uvicorn")


class NextQuestions(BaseModel):
    """A list of questions that user might ask next"""

    questions: List[str]


class NextQuestionSuggestion:
    @staticmethod
    @observe(as_type="generation", name="suggestion-generation")
    async def suggest_next_questions(
        messages: List[Message],
        number_of_questions: int = N_QUESTION_TO_GENERATE,
    ) -> List[str]:
        """
        Suggest the next questions that user might ask based on the conversation history
        Return as empty list if there is an error
        """
        try:
            # Reduce the cost by only using the last two messages
            last_user_message = None
            last_assistant_message = None
            for message in reversed(messages):
                if message.role == "user":
                    last_user_message = f"User: {message.content}"
                elif message.role == "assistant":
                    last_assistant_message = f"Assistant: {message.content}"
                if last_user_message and last_assistant_message:
                    break
            conversation: str = f"{last_user_message}\n{last_assistant_message}"

            output: NextQuestions = await Settings.llm.astructured_predict(
                NextQuestions,
                prompt=NEXT_QUESTIONS_SUGGESTION_PROMPT,
                conversation=conversation,
                number_of_questions=number_of_questions,
            )

            langfuse_context.update_current_observation(
                model=os.environ.get("MODEL", "gpt-4o-mini"),
                input=conversation,
                output=str(output.questions),
            )

            return output.questions
        except Exception as e:
            logger.error(f"Error when generating next question: {e}")
            return []
