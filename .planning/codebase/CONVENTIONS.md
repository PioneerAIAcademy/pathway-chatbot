# Coding Conventions

**Analysis Date:** 2026-01-30

## Naming Patterns

**Files:**
- Frontend: kebab-case for all files (e.g., `chat-messages.tsx`, `use-config.ts`, `chat-input.tsx`)
- Backend: snake_case for all files (e.g., `input_validator.py`, `chat_config.py`, `test_security_validation.py`)

**Functions:**
- Frontend: camelCase (e.g., `useClientConfig`, `handleSubmit`, `getBackendOrigin`, `scrollToBottom`)
- Backend: snake_case (e.g., `validate_input_security`, `get_security_message`, `analyze_risk_score`)

**Variables:**
- Frontend: camelCase (e.g., `starterQuestions`, `isAcmChecked`, `scrollableChatContainerRef`)
- Backend: snake_case (e.g., `risk_level`, `security_details`, `input_text`, `max_length`)

**Types:**
- Frontend: PascalCase for interfaces and types (e.g., `ChatHandler`, `ChatConfig`, `ButtonProps`)
- Backend: PascalCase for classes and Enums (e.g., `InputValidator`, `RiskLevel`, `SecurityValidationError`, `MessageType`)

**Constants:**
- Frontend: UPPER_SNAKE_CASE (e.g., `ALLOWED_EXTENSIONS`)
- Backend: UPPER_SNAKE_CASE (e.g., `MAX_QUESTION_LENGTH`, `PYTECTOR_AVAILABLE`, `BYTES_TO_MB`)

**Components:**
- PascalCase (e.g., `ChatMessages`, `ChatInput`, `DisclaimerMessage`, `Button`)

## Code Style

**Formatting:**
- Frontend: Prettier with `prettier-plugin-organize-imports`
- Backend: PEP 8 compliance, 4-space indentation
- Frontend indentation: 2 spaces
- Backend indentation: 4 spaces
- Frontend strings: Double quotes preferred
- Backend strings: Double quotes for docstrings, flexible for code

**Linting:**
- Frontend: ESLint with `next/core-web-vitals` and `prettier` configs
- Key rules:
  - `max-params: 4` (error level)
  - `prefer-const: error`
- Backend: No explicit linter config (uses PEP 8 standards)

## Import Organization

**Order (Frontend):**
1. External libraries (e.g., `ai/react`, `lucide-react`, React)
2. Internal components (relative or absolute with `@/`)
3. Types/interfaces
4. Hooks

Example from `frontend/app/components/chat-section.tsx`:
```typescript
import { useChat } from "ai/react";
import { useState, useEffect, useRef } from "react";
import DisclaimerMessage from "./disclaimer-message";
import Greeting from "./greeting";
import { ChatInput, ChatMessages } from "./ui/chat";
import { useClientConfig } from "./ui/chat/hooks/use-config";
```

**Order (Backend):**
1. Standard library imports
2. Third-party imports (grouped by package)
3. Local imports (grouped by module)

Example from `backend/app/security/input_validator.py`:
```python
import re
import logging
from typing import Dict, Any, Tuple
from enum import Enum

try:
    import pytector
    PYTECTOR_AVAILABLE = True
except ImportError:
    PYTECTOR_AVAILABLE = False

from ..utils.localization import LocalizationManager, MessageType
```

**Path Aliases:**
- Frontend: `@/*` maps to root directory (configured in `tsconfig.json`)
- Backend: Relative imports with `..` for parent modules

## Error Handling

**Patterns:**

**Frontend:**
- Try-catch for async operations
- Log errors with context: `console.error("Error fetching config", error)`
- Display user-friendly messages in UI
- Graceful degradation (e.g., show loading spinner, fallback to defaults)

Example from `frontend/app/components/ui/chat/chat-messages.tsx`:
```typescript
fetch(`${backend}/api/chat/config`)
  .then((response) => response.json())
  .then((data) => {
    if (data?.starterQuestions) {
      setStarterQuestions(data.starterQuestions);
    }
  })
  .catch((error) => console.error("Error fetching config", error));
```

**Backend:**
- Custom exceptions for domain errors (e.g., `SecurityValidationError`)
- Structured logging with levels: `logger.error()`, `logger.warning()`, `logger.info()`
- Include traceback for exceptions: `logger.exception()` or `exc_info=True`
- HTTPException for API errors with status codes

Example from `backend/app/api/routers/chat.py`:
```python
raise HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="Invalid input"
)
```

Example from `backend/app/security/input_validator.py`:
```python
logger.warning(f"Failed to initialize Pytector: {e}")
logger.info(f"Generated security message in {detected_lang} for blocked input")
logger.error(f"Failed to get localized security message: {e}")
```

## Logging

**Framework:**
- Frontend: `console` (error, log, warn)
- Backend: `logging` module with uvicorn logger

**Patterns:**

**Frontend:**
- Log errors during fetch operations
- Include context in error messages
- Use `console.error` for errors

**Backend:**
- Get logger: `logger = logging.getLogger("uvicorn")`
- Log at appropriate levels:
  - `logger.info()` for normal operations
  - `logger.warning()` for recoverable issues
  - `logger.error()` for errors
  - `logger.exception()` for exceptions with full traceback
- Include f-strings with context: `logger.warning(f"Failed to initialize Pytector: {e}")`
- Log security events: `logger.warning(f"Security validation blocked suspicious input - Risk: {risk_level}")`

## Comments

**When to Comment:**
- Module-level docstrings describing purpose
- Complex algorithms or security logic
- Non-obvious business rules
- Type information in TypeScript
- Workarounds or TODO items (rare)

**JSDoc/TSDoc:**
- Not heavily used in frontend
- Interfaces are self-documenting via TypeScript

**Python Docstrings:**
- Required for all public classes and functions
- Triple quotes with description
- Args and Returns sections

Example from `backend/app/security/input_validator.py`:
```python
def validate_input_security(cls, input_text: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Comprehensive security validation of user input with localized responses.
    
    Args:
        input_text: The user input to validate
        
    Returns:
        Tuple of (is_suspicious, blocked_message_or_empty, details_dict)
        - is_suspicious: True if input contains suspicious patterns
        - blocked_message_or_empty: Error message if blocked, empty string if allowed
        - details_dict: Security analysis details
    """
```

## Function Design

**Size:**
- Keep functions focused and single-purpose
- Frontend: Components under ~150 lines
- Backend: Functions under ~100 lines

**Parameters:**
- Frontend: Max 4 parameters (enforced by ESLint)
- Use destructuring for complex params
- Props interfaces for React components

Example from `frontend/app/components/ui/chat/chat-messages.tsx`:
```typescript
export default function ChatMessages(
  props: Pick<
    ChatHandler,
    "messages" | "isLoading" | "reload" | "stop" | "append" | "setMessages"
  >,
)
```

**Backend:**
- Type hints required on all parameters and return values
- Use `Tuple` for multiple return values
- Use `Optional` for nullable values

Example from `backend/app/security/input_validator.py`:
```python
@classmethod
def analyze_risk_score(cls, input_text: str) -> Tuple[int, Dict[str, Any]]:
```

**Return Values:**
- Frontend: Single values or objects; use hooks for complex state
- Backend: Tuple for multiple values (e.g., `Tuple[bool, str, Dict[str, Any]]`)

## Module Design

**Exports:**
- Frontend: Named exports for utilities, default exports for components
- Backend: Classes and functions directly

Example from `frontend/app/components/ui/button.tsx`:
```typescript
export { Button, buttonVariants };
```

**Barrel Files:**
- Used in frontend: `frontend/app/components/ui/chat/index.ts`
- Not used in backend

## TypeScript Specifics

**Strict Mode:**
- `strict: true` enabled in `tsconfig.json`
- Type all function parameters and return values
- Use interfaces for object shapes
- Use types for unions/primitives
- Avoid `any` - use `unknown` if type is truly unknown
- Use optional chaining (`?.`) and nullish coalescing (`??`)

**Component Patterns:**
- Function components with hooks
- Props defined as interfaces
- Use `React.forwardRef` for ref forwarding

Example from `frontend/app/components/ui/button.tsx`:
```typescript
export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    // implementation
  },
);
Button.displayName = "Button";
```

## Python Specifics

**Type Hints:**
- Required for all public functions
- Use from `typing` module: `List`, `Dict`, `Tuple`, `Optional`, `Any`
- Class methods use `@classmethod` decorator

**Async/Await:**
- Use `async def` for async functions
- Suffix async functions with `_async` when sync version exists

Example from `backend/app/security/input_validator.py`:
```python
@classmethod
async def validate_input_security_async(cls, input_text: str) -> Tuple[bool, str, Dict[str, Any]]:
```

**Enums:**
- Use `Enum` class for constants
- Values are string literals

Example from `backend/app/security/input_validator.py`:
```python
class RiskLevel(Enum):
    """Risk levels for input classification."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    CRITICAL = "CRITICAL"
```

---

*Convention analysis: 2026-01-30*
