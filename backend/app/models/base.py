from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    # Global Constraints do projeto: timestamps `timestamptz` (com timezone) UTC no banco.
    type_annotation_map = {
        datetime: DateTime(timezone=True),
    }
