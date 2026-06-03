"""Smart Merge System for Season-to-Season Filter Migration.

This module implements intelligent matching between old and new season filters,
allowing automatic transfer of sounds and customizations even when item names
or criteria change slightly between seasons.
"""

import re
from typing import List, Dict, Tuple, Optional
from core.data_models import FilterBlock, SimilarityMatch
from core.parser import FilterParser, SOUND_RE_CUSTOM, SOUND_RE_PLAY


class SimilarityScorer:
    """Calculates similarity scores between filter blocks.

    Uses weighted scoring across multiple dimensions:
    - Rarity (35%) - Must match for items to be similar
    - Class (25%) - Item category is very important
    - BaseType (20%) - Specific item names matter
    - Context (15%) - Other filter criteria
    - Header (5%) - Show vs Hide
    """

    # Configurable weights (must sum to 1.0)
    DEFAULT_WEIGHTS = {
        "rarity": 0.35,      # Highest priority - rarity tier must match
        "class": 0.25,       # High - item type very important
        "basetype": 0.20,    # Medium - specific items
        "context": 0.15,     # Low - other criteria
        "header": 0.05       # Very low - Show vs Hide
    }

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        """Initialize scorer with optional custom weights."""
        self.weights = weights if weights else self.DEFAULT_WEIGHTS.copy()
        self._validate_weights()

    def _validate_weights(self):
        """Ensure weights sum to 1.0."""
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total}")

    def calculate_similarity(self, block_a: FilterBlock, block_b: FilterBlock) -> float:
        """Calculate similarity score between two blocks (0.0 to 1.0).

        Args:
            block_a: First filter block
            block_b: Second filter block

        Returns:
            Similarity score from 0.0 (no match) to 1.0 (perfect match)
        """
        score = 0.0

        # Rarity match (exact or compatible)
        rarity_score = self._compare_rarity(block_a.rarity, block_b.rarity)
        score += self.weights["rarity"] * rarity_score

        # Class match (Jaccard similarity)
        class_score = self._jaccard_similarity(block_a.class_values, block_b.class_values)
        score += self.weights["class"] * class_score

        # BaseType match (Jaccard similarity)
        basetype_score = self._jaccard_similarity(block_a.basetype_values, block_b.basetype_values)
        score += self.weights["basetype"] * basetype_score

        # Context similarity (keyword matching)
        context_score = self._context_similarity(block_a.context_lines, block_b.context_lines)
        score += self.weights["context"] * context_score

        # Header match (exact)
        if block_a.header == block_b.header:
            score += self.weights["header"]

        return min(score, 1.0)

    def get_breakdown(self, block_a: FilterBlock, block_b: FilterBlock) -> Dict[str, float]:
        """Get detailed score breakdown for debugging/display.

        Returns:
            Dict mapping component names to their contribution to final score
        """
        breakdown = {}

        rarity_score = self._compare_rarity(block_a.rarity, block_b.rarity)
        breakdown["rarity"] = self.weights["rarity"] * rarity_score

        class_score = self._jaccard_similarity(block_a.class_values, block_b.class_values)
        breakdown["class"] = self.weights["class"] * class_score

        basetype_score = self._jaccard_similarity(block_a.basetype_values, block_b.basetype_values)
        breakdown["basetype"] = self.weights["basetype"] * basetype_score

        context_score = self._context_similarity(block_a.context_lines, block_b.context_lines)
        breakdown["context"] = self.weights["context"] * context_score

        breakdown["header"] = self.weights["header"] if block_a.header == block_b.header else 0.0

        return breakdown

    def classify_match(self, score: float) -> str:
        """Classify match quality based on score.

        Returns:
            "exact" (90%+), "high" (70-90%), "medium" (50-70%), or "low" (<50%)
        """
        if score >= 0.9:
            return "exact"
        elif score >= 0.7:
            return "high"
        elif score >= 0.5:
            return "medium"
        else:
            return "low"

    def _compare_rarity(self, rarity_a: str, rarity_b: str) -> float:
        """Compare rarity strings.

        Returns:
            1.0 for exact match, 0.5 for compatible, 0.0 for mismatch
        """
        if rarity_a == rarity_b:
            return 1.0

        # Check for compatible rarities (e.g., "Rarity Rare" in both)
        if self._rarity_compatible(rarity_a, rarity_b):
            return 0.5

        return 0.0

    def _rarity_compatible(self, rarity_a: str, rarity_b: str) -> bool:
        """Check if rarities share common keywords."""
        keywords_a = set(rarity_a.lower().split())
        keywords_b = set(rarity_b.lower().split())

        # Must share at least one rarity keyword
        rarity_words = {"normal", "magic", "rare", "unique"}
        common = keywords_a & keywords_b & rarity_words

        return len(common) > 0

    def _jaccard_similarity(self, list_a: List[str], list_b: List[str]) -> float:
        """Calculate Jaccard similarity coefficient for string lists.

        Formula: |A ∩ B| / |A ∪ B|

        Returns:
            Similarity from 0.0 to 1.0
        """
        if not list_a and not list_b:
            return 1.0  # Both empty = perfect match

        if not list_a or not list_b:
            return 0.0  # One empty, one not = no match

        # Case-insensitive comparison
        set_a = set(item.lower() for item in list_a)
        set_b = set(item.lower() for item in list_b)

        intersection = len(set_a & set_b)
        union = len(set_a | set_b)

        return intersection / union if union > 0 else 0.0

    def _context_similarity(self, context_a: List[str], context_b: List[str]) -> float:
        """Compare context lines by extracting and comparing keywords.

        Example: "ItemLevel >= 50" -> keyword "ItemLevel"
        """
        keywords_a = self._extract_keywords(context_a)
        keywords_b = self._extract_keywords(context_b)

        return self._jaccard_similarity(keywords_a, keywords_b)

    def _extract_keywords(self, context_lines: List[str]) -> List[str]:
        """Extract keyword from each context line (first word).

        Examples:
            "ItemLevel >= 50" -> "ItemLevel"
            "DropLevel > 10" -> "DropLevel"
        """
        keywords = []
        for line in context_lines:
            parts = line.strip().split()
            if parts:
                keywords.append(parts[0])  # First word is the keyword
        return keywords


class MatchFinder:
    """Finds best matches between old and new season filter blocks."""

    def __init__(self, scorer: Optional[SimilarityScorer] = None):
        """Initialize match finder with optional custom scorer."""
        self.scorer = scorer if scorer else SimilarityScorer()

    def find_matches(self,
                    old_blocks: List[FilterBlock],
                    new_blocks: List[FilterBlock],
                    min_confidence: float = 0.5) -> List[SimilarityMatch]:
        """Find best matches for each old block.

        Strategy: For each old block with sounds, find the best matching new block.
        Only creates matches above min_confidence threshold.

        Args:
            old_blocks: Blocks from old season filter
            new_blocks: Blocks from new season filter
            min_confidence: Minimum similarity score (0.0 to 1.0)

        Returns:
            List of SimilarityMatch objects, sorted by confidence (high to low)
        """
        matches = []

        # Only match old blocks that have sounds to transfer
        old_blocks_with_sounds = [b for b in old_blocks if b.sound_lines]

        for old_block in old_blocks_with_sounds:
            best_match = None
            best_score = min_confidence

            for new_block in new_blocks:
                score = self.scorer.calculate_similarity(old_block, new_block)
                if score > best_score:
                    best_score = score
                    best_match = new_block

            if best_match:
                score_breakdown = self.scorer.get_breakdown(old_block, best_match)
                match_type = self.scorer.classify_match(best_score)

                match = SimilarityMatch(
                    old_block=old_block,
                    new_block=best_match,
                    confidence=best_score,
                    score_breakdown=score_breakdown,
                    match_type=match_type,
                    user_approved=None  # Pending review
                )
                matches.append(match)

        # Sort by confidence (highest first)
        matches.sort(key=lambda m: m.confidence, reverse=True)

        return matches

    def get_statistics(self, matches: List[SimilarityMatch]) -> Dict[str, int]:
        """Get statistics about match quality.

        Returns:
            Dict with counts by match type
        """
        stats = {
            "total": len(matches),
            "exact": sum(1 for m in matches if m.match_type == "exact"),
            "high": sum(1 for m in matches if m.match_type == "high"),
            "medium": sum(1 for m in matches if m.match_type == "medium"),
            "low": sum(1 for m in matches if m.match_type == "low"),
            "approved": sum(1 for m in matches if m.user_approved is True),
            "rejected": sum(1 for m in matches if m.user_approved is False),
            "pending": sum(1 for m in matches if m.user_approved is None),
        }
        return stats


class MigrationExecutor:
    """Executes approved matches to create merged filter."""

    def execute_migration(self,
                         new_filter_lines: List[str],
                         matches: List[SimilarityMatch],
                         transfer_sounds: bool = True,
                         transfer_colors: bool = False) -> List[str]:
        """Apply approved matches to new filter.

        Args:
            new_filter_lines: Lines from new season filter
            matches: List of similarity matches
            transfer_sounds: Whether to transfer sound lines
            transfer_colors: Whether to transfer color data

        Returns:
            Modified filter lines with transfers applied
        """
        merged = list(new_filter_lines)

        # Only process approved matches
        approved_matches = [m for m in matches if m.user_approved is True]

        # Track cumulative offset as we insert lines
        offset = 0

        # Process matches in order by new_block start_idx to maintain proper offsets
        approved_matches.sort(key=lambda m: m.new_block.start_idx)

        for match in approved_matches:
            old_block = match.old_block
            new_block = match.new_block

            # Calculate current position with offset
            insert_at = new_block.end_idx + offset

            # Transfer sounds
            if transfer_sounds and old_block.sound_lines:
                # Detect indentation from new block
                indent = self._detect_indent(merged, new_block.start_idx + offset)

                # Insert sound lines
                for sound_line in old_block.sound_lines:
                    # Ensure proper indentation
                    clean_line = sound_line.strip()
                    new_line = f"{indent}{clean_line}\n"
                    merged.insert(insert_at, new_line)
                    insert_at += 1
                    offset += 1

            # Transfer colors (future feature)
            if transfer_colors and old_block.color_data:
                # TODO: Implement color transfer
                pass

        return merged

    def _detect_indent(self, lines: List[str], block_start_idx: int) -> str:
        """Detect indentation from block lines.

        Returns:
            Indentation string (tabs or spaces)
        """
        # Look for first indented line in block
        i = block_start_idx + 1
        while i < len(lines):
            line = lines[i]
            if line.strip():
                # Line has content
                leading = len(line) - len(line.lstrip(" \t"))
                if leading > 0:
                    return line[:leading]
            i += 1

        # Default to tab
        return "\t"


# Helper functions for converting between data structures

def parse_blocks_from_lines(lines: List[str]) -> List[FilterBlock]:
    """Parse filter lines into FilterBlock objects.

    Args:
        lines: Lines from a filter file

    Returns:
        List of FilterBlock objects
    """
    parser = FilterParser()
    return parser.parse_file(lines)


def create_match_summary(matches: List[SimilarityMatch]) -> str:
    """Create human-readable summary of matches.

    Args:
        matches: List of similarity matches

    Returns:
        Multi-line summary string
    """
    finder = MatchFinder()
    stats = finder.get_statistics(matches)

    lines = [
        f"Total Matches Found: {stats['total']}",
        f"",
        f"By Confidence:",
        f"  Exact (90%+):   {stats['exact']}",
        f"  High (70-90%):  {stats['high']}",
        f"  Medium (50-70%): {stats['medium']}",
        f"  Low (<50%):     {stats['low']}",
        f"",
        f"By Status:",
        f"  Approved: {stats['approved']}",
        f"  Rejected: {stats['rejected']}",
        f"  Pending:  {stats['pending']}",
    ]

    return "\n".join(lines)
