"""Calculator tool: evaluate one arithmetic operation on two numbers."""

import math
from typing import Literal

from anyagent.tools.decorator import tool


@tool
def calculate(
    operation: Literal["add", "subtract", "multiply", "divide"],
    a: float,
    b: float,
) -> str:
    """Calculate one arithmetic operation on two finite numbers."""
    if not math.isfinite(a) or not math.isfinite(b):
        return "Error: operands must be finite numbers."
    match operation:
        case "add":
            result = a + b
        case "subtract":
            result = a - b
        case "multiply":
            result = a * b
        case "divide":
            if b == 0:
                return "Error: division by zero."
            result = a / b
        case _:
            return "Error: unsupported operation."
    return str(result) if math.isfinite(result) else "Error: result is not finite."
