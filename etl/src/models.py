from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class CaseIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    case_number: str
    source: str = "unknown"
    title: Optional[str] = None
    court: Optional[str] = None
    filing_date: Optional[date] = None
    judgment_date: Optional[date] = None
    amount_awarded: Optional[float] = None
    currency: str = "USD"


class EntityIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    case_id: Optional[str] = None
    role: Optional[str] = None
    name_full: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    business_name: Optional[str] = None
    ein_or_ssn: Optional[str] = None
    address: Optional[Dict[str, Any]] = None
    phones: Optional[List[str]] = None
    emails: Optional[List[str]] = None
