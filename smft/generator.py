import json
import random
import time
import uuid
from typing import Dict, Any


# Pre-generate constants for faster access
CITIES = ["GOROD BEREZNI", "MOSCOW", "SAINT PETERSBURG", "NOVOSIBIRSK", "YEKATERINBURG", "KAZAN"]
TRANSACTION_TYPES = ["transfer", "withdrawal", "purchase", "deposit", "payment"]
MCC_CODES = ["5411", "5912", "5813", "4121", "7011", "5542", "5999"]


async def generate_transaction_event() -> Dict[str, Any]:
    """Generate a random transaction event based on the provided example."""
    
    # Use faster random number generation
    r = random.Random()
    
    # Generate random card number using format string
    cardnumber = f"4276{r.randint(100000000000, 999999999999)}"
    
    # Generate IDs using format strings
    consumer_id = f"{r.randint(10000000000, 99999999999)}"
    client_transaction_id = f"{r.randint(10000000000, 99999999999)}"
    atm_merchant_id = f"{r.randint(100000, 999999)}"
    
    return {
        "event_id": uuid.uuid4().hex,
        "cardnumber": cardnumber,
        "timestamp": int(time.time()),
        "consumer_id": consumer_id,
        "client_transaction_id": client_transaction_id,
        "card_issuer_country": "RU",
        "card_currency": "810",
        "acquirer_institution_id": str(r.randint(1000, 9999)),
        "issuerInstitution_id": str(r.randint(2000, 9999)),
        "atm_merchant_id": atm_merchant_id,
        "atm_terminal_city": r.choice(CITIES),
        "currency": "810",
        "terminal_type": str(r.randint(0, 2)),
        "atm_mcc": r.choice(MCC_CODES),
        "cardIssuer_system": str(r.randint(1, 3)),
        "atm_terminal_country": "C",
        "transaction_type_name": r.choice(TRANSACTION_TYPES),
        "transaction_rur_amt": str(r.randint(100, 50000))
    }


async def generate_transaction_json() -> str:
    """Generate a transaction event as JSON string."""
    event = await generate_transaction_event()
    return json.dumps(event)


# Synchronous versions for backward compatibility
def generate_transaction_event_sync() -> Dict[str, Any]:
    """Synchronous version of generate_transaction_event."""
    r = random.Random()
    
    cardnumber = f"4276{r.randint(100000000000, 999999999999)}"
    consumer_id = f"{r.randint(10000000000, 99999999999)}"
    client_transaction_id = f"{r.randint(10000000000, 99999999999)}"
    atm_merchant_id = f"{r.randint(100000, 999999)}"
    
    return {
        "event_id": uuid.uuid4().hex,
        "cardnumber": cardnumber,
        "timestamp": int(time.time()),
        "consumer_id": consumer_id,
        "client_transaction_id": client_transaction_id,
        "card_issuer_country": "RU",
        "card_currency": "810",
        "acquirer_institution_id": str(r.randint(1000, 9999)),
        "issuerInstitution_id": str(r.randint(2000, 9999)),
        "atm_merchant_id": atm_merchant_id,
        "atm_terminal_city": r.choice(CITIES),
        "currency": "810",
        "terminal_type": str(r.randint(0, 2)),
        "atm_mcc": r.choice(MCC_CODES),
        "cardIssuer_system": str(r.randint(1, 3)),
        "atm_terminal_country": "C",
        "transaction_type_name": r.choice(TRANSACTION_TYPES),
        "transaction_rur_amt": str(r.randint(100, 50000))
    }


if __name__ == "__main__":
    # Example usage
    event = generate_transaction_event_sync()
    print(json.dumps(event, indent=2))