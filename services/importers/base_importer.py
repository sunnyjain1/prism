from abc import ABC, abstractmethod
from typing import List, Dict, Any
from schemas import TransactionCreate

class BaseImporter(ABC):
    @abstractmethod
    def parse(self, file_content: bytes) -> List[TransactionCreate]:
        """Parse file content and return a list of TransactionCreate objects."""
        pass

    @abstractmethod
    def validate(self, data: List[Dict[str, Any]]) -> bool:
        """Validate the structure of the incoming data."""
        pass
