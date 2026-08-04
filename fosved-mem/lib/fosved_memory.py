"""
FosvedMemory — Memanto-style typed persistent memory for Fosved Office.

Adapted from Memanto (remember/recall/answer + 13 types + temporal decay + provenance).

Usage:
    mem = FosvedMemory()
    mem.remember("bin/mlog contains 66 builtins", "fact", 1.0, "architecture")
    results = mem.recall("builtins", type_filter="fact")
    answer = mem.answer("How many builtins does mlog have?")
"""

import sqlite3
import time
import json
import re
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("fosved.memory")


class FosvedMemory:
    """Typed persistent memory with 13 types, temporal decay, conflict detection."""

    TYPES = [
        'fact', 'decision', 'instruction', 'goal', 'preference',
        'error', 'learning', 'context', 'artifact', 'relationship',
        'observation', 'commitment', 'pattern'
    ]

    # Types that should NOT decay — owner decisions, instructions, preferences are permanent
    ETERNAL_TYPES = {'decision', 'instruction', 'preference'}

    # Decay rates: type -> (decay_per_day, floor)
    DECAY_RATES = {
        'error': (0.005, 0.5),
        'learning': (0.005, 0.5),
        'observation': (0.02, 0.2),
        'context': (0.02, 0.2),
        'pattern': (0.03, 0.1),
        'fact': (0.03, 0.1),
        'goal': (0.01, 0.3),
        'artifact': (0.01, 0.3),
        'relationship': (0.01, 0.3),
        'commitment': (0.01, 0.3),
    }

    def __init__(self, db_path: str = 'data/memory.db'):
        self.db_path = db_path
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._ensure_tables()

    def _ensure_tables(self):
        """Create tables if they don't exist."""
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS typed_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                type TEXT NOT NULL,
                confidence REAL DEFAULT 0.8,
                source TEXT DEFAULT NULL,
                version INTEGER DEFAULT 1,
                created_at REAL,
                superseded_by INTEGER DEFAULT NULL,
                metadata_json TEXT DEFAULT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_mem_type ON typed_memories(type);
            CREATE INDEX IF NOT EXISTS idx_mem_created ON typed_memories(created_at);
            CREATE INDEX IF NOT EXISTS idx_mem_source ON typed_memories(source);
            CREATE INDEX IF NOT EXISTS idx_mem_superseded ON typed_memories(superseded_by);
        ''')
        self.db.commit()

    # ─── REMEMBER ────────────────────────────────────────────────────────────

    def remember(
        self,
        content: str,
        mem_type: str,
        confidence: float = 0.8,
        source: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Save a new memory. Returns the new memory ID.

        If a conflicting memory exists of the same type, the old one is
        marked as superseded (versioned, not deleted).
        """
        if mem_type not in self.TYPES:
            logger.warning(f"Unknown memory type '{mem_type}', using 'fact'")
            mem_type = 'fact'

        confidence = max(0.0, min(1.0, confidence))

        # Check for conflicts — same type, similar topic
        existing = self.recall(content, type_filter=mem_type, limit=5)
        for m in existing:
            if self._contradicts(m['content'], content):
                # Version the old one: mark as superseded
                self.db.execute(
                    'UPDATE typed_memories SET superseded_by = -1 WHERE id = ?',
                    (m['id'],)
                )
                logger.info(
                    f"Superseded memory #{m['id']} (type={mem_type}) "
                    f"due to conflict with new content"
                )

        now = time.time()
        meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

        cursor = self.db.execute(
            '''INSERT INTO typed_memories
               (content, type, confidence, source, created_at, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (content, mem_type, confidence, source, now, meta_json)
        )
        self.db.commit()

        new_id = cursor.lastrowid
        logger.info(f"remember [{mem_type}] #{new_id}: {content[:80]}")
        return new_id

    # ─── RECALL ─────────────────────────────────────────────────────────────

    def recall(
        self,
        query: str,
        type_filter: Optional[str] = None,
        min_confidence: float = 0.3,
        limit: int = 10,
        include_superseded: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Recall memories matching query. Uses substring matching (case-insensitive).
        Returns list of dicts, sorted by relevance (temporal decay applied).

        Args:
            query: Search query (matched against content, case-insensitive)
            type_filter: Only return memories of this type
            min_confidence: Minimum confidence threshold
            limit: Max results
            include_superseded: If True, include superseded memories
        """
        if type_filter and type_filter not in self.TYPES:
            logger.warning(f"Unknown type_filter '{type_filter}', ignoring")
            type_filter = None

        sql = 'SELECT * FROM typed_memories WHERE confidence >= ?'
        params: list = [min_confidence]

        if not include_superseded:
            sql += ' AND superseded_by IS NULL'

        if type_filter:
            sql += ' AND type = ?'
            params.append(type_filter)

        # Substring match — case-insensitive
        sql += ' AND lower(content) LIKE ?'
        params.append(f'%{query.lower()}%')

        sql += ' ORDER BY created_at DESC LIMIT ?'
        params.append(limit)

        rows = self.db.execute(sql, params).fetchall()
        results = [dict(r) for r in rows]

        # Apply temporal decay scoring
        now = time.time()
        for m in results:
            m['relevance'] = self._relevance_score(m, query, now)

        # Sort by relevance descending
        results.sort(key=lambda x: x['relevance'], reverse=True)
        return results

    def recall_all_types(self, query: str, min_confidence: float = 0.3, limit: int = 20) -> List[Dict[str, Any]]:
        """Recall across ALL types, grouped."""
        return self.recall(query, type_filter=None, min_confidence=min_confidence, limit=limit)

    def recall_by_source(self, source: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Recall all memories from a specific source."""
        rows = self.db.execute(
            '''SELECT * FROM typed_memories
               WHERE source = ? AND superseded_by IS NULL
               ORDER BY created_at DESC LIMIT ?''',
            (source, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── ANSWER ─────────────────────────────────────────────────────────────

    def answer(self, question: str) -> str:
        """
        RAG-style answer: recall relevant memories → format grounded answer.
        Returns formatted context string (LLM prompt-ready).
        """
        memories = self.recall(question, limit=10)
        if not memories:
            return "No relevant memories found."

        lines = []
        for m in memories:
            ts = time.strftime('%Y-%m-%d %H:%M', time.localtime(m['created_at']))
            lines.append(
                f"[{m['type']}, conf:{m['confidence']:.1f}, {ts}, src:{m['source'] or '?'}] "
                f"{m['content']}"
            )
        return '\n'.join(lines)

    # ─── CONFLICT DETECTION ─────────────────────────────────────────────────

    def detect_conflicts(self, type_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Find contradictions between active memories of the same type.
        Returns list of conflict dicts with both memories and resolution hint.
        """
        sql = 'SELECT * FROM typed_memories WHERE superseded_by IS NULL'
        params: list = []
        if type_filter:
            sql += ' AND type = ?'
            params.append(type_filter)
        rows = self.db.execute(sql, params).fetchall()
        all_mems = [dict(r) for r in rows]

        conflicts = []
        seen_types: Dict[str, list] = {}
        for m in all_mems:
            seen_types.setdefault(m['type'], []).append(m)

        for mem_type, mems in seen_types.items():
            for i, a in enumerate(mems):
                for b in mems[i + 1:]:
                    if self._similar_topic(a['content'], b['content']) and \
                       self._contradicts(a['content'], b['content']):
                        resolution = 'keep_newer' if a['created_at'] < b['created_at'] else 'keep_older'
                        conflicts.append({
                            'memory_a': a,
                            'memory_b': b,
                            'resolution': resolution,
                            'type': mem_type
                        })

        return conflicts

    def resolve_conflict(self, keep_id: int, supersede_id: int):
        """Manually resolve a conflict: supersede one memory in favor of another."""
        self.db.execute(
            'UPDATE typed_memories SET superseded_by = ? WHERE id = ?',
            (keep_id, supersede_id)
        )
        self.db.commit()
        logger.info(f"Resolved conflict: kept #{keep_id}, superseded #{supersede_id}")

    # ─── TEMPORAL DECAY ────────────────────────────────────────────────────

    def _relevance_score(self, memory: Dict[str, Any], query: str, now: float) -> float:
        """
        Calculate relevance score: semantic match * temporal decay * confidence.
        Decisions, instructions, preferences don't decay (eternal).
        """
        # Simple substring relevance
        content_lower = memory['content'].lower()
        query_lower = query.lower()
        if query_lower in content_lower:
            semantic = 1.0
        else:
            # Check individual words
            words = query_lower.split()
            matches = sum(1 for w in words if w in content_lower and len(w) > 2)
            semantic = matches / max(len(words), 1)

        if memory['type'] in self.ETERNAL_TYPES:
            decay = 1.0
        elif memory['type'] in self.DECAY_RATES:
            rate, floor = self.DECAY_RATES[memory['type']]
            age_days = (now - memory['created_at']) / 86400
            decay = max(floor, 1.0 - age_days * rate)
        else:
            decay = max(0.3, 1.0 - ((now - memory['created_at']) / 86400) * 0.02)

        return semantic * decay * memory['confidence']

    # ─── DAILY MAINTENANCE ─────────────────────────────────────────────────

    def daily_summary(self) -> Dict[str, Any]:
        """Summary of the last 24h: new memories, superseded, conflicts."""
        since = time.time() - 86400

        new_rows = self.db.execute(
            'SELECT type, COUNT(*) as cnt FROM typed_memories WHERE created_at > ? GROUP BY type',
            (since,)
        ).fetchall()

        superseded_rows = self.db.execute(
            '''SELECT type, COUNT(*) as cnt FROM typed_memories
               WHERE superseded_by IS NOT NULL AND superseded_by != -1
               AND created_at > ? GROUP BY type''',
            (since,)
        ).fetchall()

        conflicts = self.detect_conflicts()

        return {
            'new_memories': {r['type']: r['cnt'] for r in new_rows},
            'superseded': {r['type']: r['cnt'] for r in superseded_rows},
            'conflicts_count': len(conflicts),
            'conflicts': conflicts[:5],  # top 5
            'total_active': self.db.execute(
                'SELECT COUNT(*) FROM typed_memories WHERE superseded_by IS NULL'
            ).fetchone()[0]
        }

    def nightly_maintenance(self) -> str:
        """
        Nightly cleanup:
        1. Detect and log conflicts
        2. Clean stale observations (30+ days, confidence < 0.5)
        3. Return summary for admin
        """
        summary = self.daily_summary()

        # Clean stale observations
        cutoff = time.time() - 30 * 86400
        deleted = self.db.execute(
            '''DELETE FROM typed_memories
               WHERE type = 'observation' AND confidence < 0.5 AND created_at < ?''',
            (cutoff,)
        ).rowcount
        self.db.commit()

        # Clean stale patterns (60+ days, confidence < 0.3)
        cutoff_p = time.time() - 60 * 86400
        deleted_p = self.db.execute(
            '''DELETE FROM typed_memories
               WHERE type = 'pattern' AND confidence < 0.3 AND created_at < ?''',
            (cutoff_p,)
        ).rowcount
        self.db.commit()

        lines = [
            f"=== Fosved Memory Nightly Maintenance ===",
            f"Active memories: {summary['total_active']}",
            f"New today: {summary['new_memories']}",
            f"Conflicts: {summary['conflicts_count']}",
            f"Cleaned stale observations: {deleted}",
            f"Cleaned stale patterns: {deleted_p}",
        ]

        if summary['conflicts']:
            lines.append(f"\nConflicts requiring attention:")
            for c in summary['conflicts']:
                lines.append(
                    f"  [{c['type']}] {c['memory_a']['content'][:60]} "
                    f"vs {c['memory_b']['content'][:60]} → {c['resolution']}"
                )

        return '\n'.join(lines)

    # ─── SEED / BULK IMPORT ────────────────────────────────────────────────

    def seed(self, memories: List[Dict[str, Any]]) -> int:
        """
        Bulk import memories. Each dict needs: content, type, confidence, source.
        Skips if a very similar memory already exists.
        Returns count of actually inserted memories.
        """
        inserted = 0
        for m in memories:
            # Skip if very similar content already exists
            existing = self.recall(m['content'][:30], type_filter=m['type'], limit=1)
            if existing and self._similar_topic(existing[0]['content'], m['content']):
                logger.debug(f"Seed skip (exists): {m['content'][:60]}")
                continue

            self.remember(
                content=m['content'],
                mem_type=m['type'],
                confidence=m.get('confidence', 0.8),
                source=m.get('source', 'seed')
            )
            inserted += 1

        logger.info(f"Seed complete: {inserted}/{len(memories)} memories inserted")
        return inserted

    # ─── STATS ─────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Memory statistics."""
        total = self.db.execute(
            'SELECT COUNT(*) FROM typed_memories WHERE superseded_by IS NULL'
        ).fetchone()[0]

        by_type = self.db.execute(
            '''SELECT type, COUNT(*) as cnt, AVG(confidence) as avg_conf
               FROM typed_memories WHERE superseded_by IS NULL
               GROUP BY type ORDER BY cnt DESC'''
        ).fetchall()

        return {
            'total_active': total,
            'by_type': {r['type']: {'count': r['cnt'], 'avg_confidence': round(r['avg_conf'], 2)} for r in by_type}
        }

    # ─── INTERNAL HELPERS ──────────────────────────────────────────────────

    def _contradicts(self, text_a: str, text_b: str) -> bool:
        """
        Simple contradiction detection.
        Checks if two texts talk about the same entity but with different values.
        """
        # Extract numbers
        nums_a = set(re.findall(r'\d+\.?\d*', text_a))
        nums_b = set(re.findall(r'\d+\.?\d*', text_b))

        if nums_a and nums_b and nums_a != nums_b:
            # Same topic (similar words) but different numbers → likely contradiction
            if self._similar_topic(text_a, text_b):
                return True

        # Check for negation patterns: "X does Y" vs "X does NOT Y"
        words_a = set(re.findall(r'\b\w{4,}\b', text_a.lower()))
        words_b = set(re.findall(r'\b\w{4,}\b', text_b.lower()))
        common = words_a & words_b

        if len(common) >= 3:
            # Check if one has negation and the other doesn't
            has_not_a = bool(re.search(r'\b(не|no|not|never|без)\b', text_a.lower()))
            has_not_b = bool(re.search(r'\b(не|no|not|never|без)\b', text_b.lower()))
            if has_not_a != has_not_b:
                return True

        return False

    def _similar_topic(self, text_a: str, text_b: str) -> bool:
        """Check if two texts are about the same topic (word overlap)."""
        words_a = set(re.findall(r'\b\w{4,}\b', text_a.lower()))
        words_b = set(re.findall(r'\b\w{4,}\b', text_b.lower()))
        if not words_a or not words_b:
            return False
        common = words_a & words_b
        # At least 30% overlap of the smaller set
        min_size = min(len(words_a), len(words_b))
        return len(common) / max(min_size, 1) >= 0.3

    def close(self):
        """Close the database connection."""
        self.db.close()