from datetime import date, datetime
from decimal import Decimal
from uuid import UUID


def wire(value):
    """Preserva centavos como strings no JSON, inclusive em objetos aninhados."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(item) for item in value]
    return value
