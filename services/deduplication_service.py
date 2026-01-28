"""
Transaction deduplication service to prevent importing duplicate transactions.
"""
from typing import List, Set, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Transaction
from schemas import TransactionCreate
import logging

logger = logging.getLogger(__name__)


class DeduplicationService:
    """Service to detect and filter duplicate transactions."""
    
    def __init__(self, db: Session, owner_id: str):
        self.db = db
        self.owner_id = owner_id
    
    def find_duplicates(
        self, 
        new_transactions: List[TransactionCreate],
        similarity_threshold: float = 0.95
    ) -> Tuple[List[TransactionCreate], List[TransactionCreate]]:
        """
        Find duplicate transactions by comparing with existing transactions.
        
        Args:
            new_transactions: List of new transactions to check
            similarity_threshold: Threshold for considering transactions as duplicates (0-1)
            
        Returns:
            Tuple of (unique_transactions, duplicate_transactions)
        """
        if not new_transactions:
            return [], []
        
        # Get existing transactions in the date range of new transactions
        dates = [tx.date for tx in new_transactions if tx.date]
        if not dates:
            return new_transactions, []
        
        min_date = min(dates) - timedelta(days=1)
        max_date = max(dates) + timedelta(days=1)
        
        existing_txs = self.db.query(Transaction).filter(
            Transaction.owner_id == self.owner_id,
            Transaction.date >= min_date,
            Transaction.date <= max_date
        ).all()
        
        unique_txs = []
        duplicate_txs = []
        
        for new_tx in new_transactions:
            is_duplicate = False
            
            for existing_tx in existing_txs:
                if self._are_duplicates(new_tx, existing_tx, similarity_threshold):
                    is_duplicate = True
                    logger.debug(f"Found duplicate: {new_tx.description} - ${new_tx.amount} on {new_tx.date}")
                    break
            
            if is_duplicate:
                duplicate_txs.append(new_tx)
            else:
                unique_txs.append(new_tx)
        
        return unique_txs, duplicate_txs
    
    def _are_duplicates(
        self, 
        tx1: TransactionCreate, 
        tx2: Transaction, 
        threshold: float
    ) -> bool:
        """
        Check if two transactions are duplicates.
        
        Criteria:
        1. Same date (within 1 day)
        2. Same amount (within small tolerance)
        3. Similar description
        """
        # Check date (within 1 day)
        date_diff = abs((tx1.date - tx2.date).days)
        if date_diff > 1:
            return False
        
        # Check amount (within 0.01 tolerance for floating point)
        amount_diff = abs(tx1.amount - tx2.amount)
        if amount_diff > 0.01:
            return False
        
        # Check description similarity
        desc1 = tx1.description.lower().strip()
        desc2 = tx2.description.lower().strip()
        
        # Exact match
        if desc1 == desc2:
            return True
        
        # Similarity check (simple word overlap)
        words1 = set(desc1.split())
        words2 = set(desc2.split())
        
        if not words1 or not words2:
            return False
        
        # Calculate Jaccard similarity
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        similarity = intersection / union if union > 0 else 0
        
        return similarity >= threshold
    
    def remove_duplicates_within_batch(
        self, 
        transactions: List[TransactionCreate]
    ) -> List[TransactionCreate]:
        """
        Remove duplicates within the same batch of transactions.
        
        Args:
            transactions: List of transactions to deduplicate
            
        Returns:
            List of unique transactions
        """
        seen = set()
        unique = []
        
        for tx in transactions:
            # Create a signature for the transaction
            signature = self._create_signature(tx)
            
            if signature not in seen:
                seen.add(signature)
                unique.append(tx)
            else:
                logger.debug(f"Removed duplicate within batch: {tx.description} - ${tx.amount} on {tx.date}")
        
        return unique
    
    def _create_signature(self, tx: TransactionCreate) -> str:
        """Create a signature for a transaction to detect duplicates."""
        # Normalize date to day (ignore time)
        date_str = tx.date.strftime("%Y-%m-%d")
        
        # Round amount to 2 decimal places
        amount_str = f"{tx.amount:.2f}"
        
        # Normalize description (lowercase, remove extra spaces)
        desc = ' '.join(tx.description.lower().split())
        
        return f"{date_str}|{amount_str}|{desc}"
