"""
Instructor mixin for adding structured output support to LLM clients.
"""
import instructor
import structlog
from typing import TypeVar, Type, Optional, Any, Union
from pydantic import BaseModel

log = structlog.get_logger("talemate.client.instructor")

T = TypeVar('T', bound=BaseModel)


class InstructorMixin:
    """
    Mixin to add instructor support to any client that uses OpenAI-compatible API.
    
    This mixin provides the generate_structured method which uses instructor
    to parse and validate responses according to Pydantic models.
    """
    
    def setup_instructor(self):
        """
        Initialize instructor client. Should be called in set_client method
        after the main client is initialized.
        """
        if hasattr(self, 'client') and self.client:
            try:
                # Detect client type and use appropriate instructor initialization
                client_module = self.client.__class__.__module__
                
                if 'anthropic' in client_module:
                    # Anthropic client
                    self.instructor_client = instructor.from_anthropic(self.client)
                    self.instructor_enabled = True
                    log.debug(f"Instructor enabled for Anthropic client: {self.__class__.__name__}")
                elif 'google' in client_module and hasattr(self.client, 'models'):
                    # Google Generative AI client
                    self.instructor_client = instructor.from_gemini(
                        client=self.client,
                        mode=instructor.Mode.GEMINI_JSON
                    )
                    self.instructor_enabled = True
                    log.debug(f"Instructor enabled for Google client: {self.__class__.__name__}")
                else:
                    # Default to OpenAI-compatible clients
                    self.instructor_client = instructor.from_openai(self.client)
                    self.instructor_enabled = True
                    log.debug(f"Instructor enabled for OpenAI-compatible client: {self.__class__.__name__}")
            except Exception as e:
                self.instructor_enabled = False
                log.error(f"Failed to setup instructor for {self.__class__.__name__}", error=str(e))
        else:
            self.instructor_enabled = False
    
    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        kind: str,
        max_retries: int = 3,
        **parameters
    ) -> T:
        """
        Generate a structured response using instructor.
        
        Args:
            prompt: The prompt to send to the model
            response_model: Pydantic model class defining the expected response structure
            kind: The type of generation (same as generate method)
            max_retries: Number of retries for validation errors
            **parameters: Additional parameters to pass to the model
            
        Returns:
            Instance of response_model with validated data
            
        Raises:
            Exception: If instructor is not enabled or generation fails
        """
        if not getattr(self, 'instructor_enabled', False):
            raise Exception(f"Instructor not enabled for {self.__class__.__name__}")
        
        # Instructor handles structured output, so we don't need any special markers
        messages = [
            {"role": "system", "content": self.get_system_message(kind)},
            {"role": "user", "content": prompt.strip()}
        ]
        
        self.log.debug(
            "generate_structured",
            prompt=prompt[:128] + " ...",
            response_model=response_model.__name__,
            parameters=parameters,
        )
        
        try:
            # Use instructor's unified interface - it handles all backend differences
            response = await self.instructor_client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                response_model=response_model,
                max_retries=max_retries,
                **parameters
            )
            
            # Update token tracking if available
            if hasattr(self, 'update_request_tokens'):
                # Estimate tokens for structured response
                response_str = response.model_dump_json() if hasattr(response, 'model_dump_json') else str(response)
                self.update_request_tokens(self.count_tokens(response_str))
            
            return response
            
        except Exception as e:
            self.log.error(
                "generate_structured error",
                error=str(e),
                response_model=response_model.__name__
            )
            raise
    
    async def generate_structured_or_fallback(
        self,
        prompt: str,
        response_model: Type[T],
        kind: str,
        fallback: bool = True,
        **parameters
    ) -> Union[T, str]:
        """
        Try to generate structured response, fallback to regular generate if it fails.
        
        Args:
            prompt: The prompt
            response_model: Expected response model
            kind: Generation type
            fallback: Whether to fallback to regular generate on failure
            **parameters: Model parameters
            
        Returns:
            Either structured response or string response
        """
        try:
            return await self.generate_structured(
                prompt=prompt,
                response_model=response_model,
                kind=kind,
                **parameters
            )
        except Exception as e:
            if fallback and hasattr(self, 'generate'):
                self.log.warning(
                    "Falling back to regular generate",
                    error=str(e),
                    response_model=response_model.__name__
                )
                return await self.generate(prompt, parameters, kind)
            else:
                raise