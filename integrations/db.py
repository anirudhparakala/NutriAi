import sqlite3
import json
import time
import os
from typing import List, Dict, Optional

DB_PATH = "nutri_ai.db"
SCHEMA_VERSION = 2  # Bump this when making schema changes


def get_schema_version(con):
    """Get current schema version from database."""
    try:
        cur = con.cursor()
        cur.execute("SELECT version FROM schema_version ORDER BY id DESC LIMIT 1")
        result = cur.fetchone()
        return result[0] if result else 0
    except sqlite3.OperationalError:
        # Table doesn't exist, schema version is 0
        return 0


def set_schema_version(con, version):
    """Set schema version in database."""
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS schema_version (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version INTEGER NOT NULL,
        migrated_at REAL NOT NULL
    )""")
    cur.execute("INSERT INTO schema_version (version, migrated_at) VALUES (?, ?)", (version, time.time()))
    con.commit()


def migrate_schema(con):
    """Run migrations to bring database up to current schema version."""
    current_version = get_schema_version(con)
    cur = con.cursor()

    if current_version < 1:
        # Migration 1: Initial schema with metadata columns
        print("Running migration 1: Adding metadata columns to sessions table")
        try:
            cur.execute("ALTER TABLE sessions ADD COLUMN model_name TEXT")
            cur.execute("ALTER TABLE sessions ADD COLUMN prompt_version TEXT")
            cur.execute("ALTER TABLE sessions ADD COLUMN generation_config_json TEXT")
            con.commit()
            set_schema_version(con, 1)
            print("Migration 1 complete")
        except sqlite3.OperationalError as e:
            # Column might already exist
            print(f"Migration 1 skipped or already applied: {e}")
            set_schema_version(con, 1)

    if current_version < 2:
        # Migration 2: Future migrations go here
        # For now, just bump version
        set_schema_version(con, 2)

    print(f"Database schema is at version {SCHEMA_VERSION}")


def init():
    """Initialize the database with required tables, indices, and WAL mode."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Enable WAL mode for better concurrency (one-time setting, persists)
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")

    # Create sessions table for logging each analysis session
    cur.execute("""CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at REAL NOT NULL,
        dish TEXT NOT NULL,
        portion_guess_g REAL NOT NULL,
        ingredients_json TEXT NOT NULL,
        refinements_json TEXT,
        final_json TEXT,
        confidence_score REAL DEFAULT 0.5,
        tool_calls_count INTEGER DEFAULT 0,
        model_name TEXT,
        prompt_version TEXT,
        generation_config_json TEXT
    )""")

    # Create assumptions table for tracking common assumptions and their accuracy
    cur.execute("""CREATE TABLE IF NOT EXISTS assumptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER,
        assumption_key TEXT NOT NULL,
        assumption_value TEXT NOT NULL,
        confidence REAL NOT NULL,
        created_at REAL NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    )""")

    # Create search_queries table for tracking what searches were performed
    cur.execute("""CREATE TABLE IF NOT EXISTS search_queries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER,
        query TEXT NOT NULL,
        results_count INTEGER NOT NULL,
        created_at REAL NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    )""")

    # Create usda_candidates table for explainability (P2-E2)
    cur.execute("""CREATE TABLE IF NOT EXISTS usda_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER,
        ingredient_name TEXT NOT NULL,
        candidate_rank INTEGER NOT NULL,
        fdc_id INTEGER,
        description TEXT,
        score REAL,
        data_type TEXT,
        selected BOOLEAN DEFAULT 0,
        created_at REAL NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    )""")

    # Create indices for query performance
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_dish ON sessions(dish);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_assumptions_session ON assumptions(session_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_searches_session ON search_queries(session_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_usda_candidates_session ON usda_candidates(session_id);")

    con.commit()

    # Run migrations to ensure schema is up to date
    migrate_schema(con)

    con.close()
    # Only log database creation, not every table check
    if not hasattr(init, '_already_logged'):
        print(f"Database initialized at {DB_PATH}")
        init._already_logged = True


def log_session(estimate, refinements=None, final_json=None, tool_calls_count=0, metadata=None) -> int:
    """
    Log a complete analysis session.

    Args:
        estimate: VisionEstimate object from initial analysis
        refinements: List of RefinementUpdate objects (optional)
        final_json: Final JSON breakdown string (optional)
        tool_calls_count: Number of tool calls made during session
        metadata: Dict with model_name, prompt_version, generation_config (optional)

    Returns:
        Session ID of the logged session
    """
    # Ensure database exists
    if not os.path.exists(DB_PATH):
        init()

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Calculate confidence score based on critical questions and refinements
    confidence_score = calculate_confidence_score(estimate, refinements)

    # Prepare JSON data
    ingredients_json = json.dumps([
        ingredient.model_dump() if hasattr(ingredient, 'model_dump') else ingredient
        for ingredient in estimate.ingredients
    ])

    refinements_json = None
    if refinements:
        refinements_json = json.dumps([
            refinement.model_dump() if hasattr(refinement, 'model_dump') else refinement
            for refinement in refinements
        ])

    # Extract metadata if provided
    model_name = None
    prompt_version = None
    generation_config_json = None
    if metadata:
        model_name = metadata.get('model_name')
        prompt_version = metadata.get('prompt_version')
        generation_config = metadata.get('generation_config')
        if generation_config:
            generation_config_json = json.dumps(generation_config)

    # Insert session record
    cur.execute("""INSERT INTO sessions
                   (created_at, dish, portion_guess_g, ingredients_json, refinements_json,
                    final_json, confidence_score, tool_calls_count,
                    model_name, prompt_version, generation_config_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
        time.time(),
        estimate.dish,
        estimate.portion_guess_g,
        ingredients_json,
        refinements_json,
        final_json or "",
        confidence_score,
        tool_calls_count,
        model_name,
        prompt_version,
        generation_config_json
    ))

    session_id = cur.lastrowid

    # Log critical questions as assumptions
    for question in estimate.critical_questions:
        cur.execute("""INSERT INTO assumptions
                       (session_id, assumption_key, assumption_value, confidence, created_at)
                       VALUES (?, ?, ?, ?, ?)""", (
            session_id,
            question.id,
            question.default or "",
            question.impact_score,
            time.time()
        ))

    # Log refinement assumptions if available
    if refinements:
        for refinement in refinements:
            if hasattr(refinement, 'updated_assumptions'):
                for assumption in refinement.updated_assumptions:
                    cur.execute("""INSERT INTO assumptions
                                   (session_id, assumption_key, assumption_value, confidence, created_at)
                                   VALUES (?, ?, ?, ?, ?)""", (
                        session_id,
                        assumption.key,
                        assumption.value,
                        assumption.confidence,
                        time.time()
                    ))

    con.commit()
    con.close()

    print(f"Logged session {session_id}: '{estimate.dish}' with confidence {confidence_score:.2f}")
    return session_id


def log_search_query(session_id: int, query: str, results_count: int):
    """
    Log a search query performed during a session.

    Args:
        session_id: ID of the session
        query: Search query string
        results_count: Number of results returned
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("""INSERT INTO search_queries
                   (session_id, query, results_count, created_at)
                   VALUES (?, ?, ?, ?)""", (
        session_id,
        query,
        results_count,
        time.time()
    ))

    con.commit()
    con.close()


def log_usda_candidates(session_id: int, ingredient_name: str, candidates: List[Dict], selected_fdc_id: Optional[int] = None):
    """
    Log USDA candidate matches for explainability (P2-E2).

    Args:
        session_id: ID of the session
        ingredient_name: Name of the ingredient that was searched
        candidates: List of top-3 candidate dicts with fdcId, description, score, dataType
        selected_fdc_id: FDC ID of the selected candidate (if any)
    """
    if not candidates:
        return

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    for rank, candidate in enumerate(candidates, start=1):
        fdc_id = candidate.get('fdcId')
        is_selected = (fdc_id == selected_fdc_id) if selected_fdc_id else (rank == 1)

        cur.execute("""INSERT INTO usda_candidates
                       (session_id, ingredient_name, candidate_rank, fdc_id, description,
                        score, data_type, selected, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            session_id,
            ingredient_name,
            rank,
            fdc_id,
            candidate.get('description', ''),
            candidate.get('score', 0.0),
            candidate.get('dataType', ''),
            is_selected,
            time.time()
        ))

    con.commit()
    con.close()
    print(f"DEBUG: Logged {len(candidates)} USDA candidates for '{ingredient_name}' in session {session_id}")


def calculate_confidence_score(estimate, refinements=None) -> float:
    """
    Calculate a confidence score for the session based on various factors.

    Args:
        estimate: VisionEstimate object
        refinements: List of refinements (optional)

    Returns:
        Confidence score between 0.0 and 1.0
    """
    score = 0.5  # Base score

    # Factor in critical questions - fewer high-impact questions = higher confidence
    if estimate.critical_questions:
        avg_impact = sum(q.impact_score for q in estimate.critical_questions) / len(estimate.critical_questions)
        score -= (avg_impact * 0.2)  # Reduce score for high-impact unknowns

    # Factor in number of ingredients - more ingredients = potentially lower confidence
    ingredient_count = len(estimate.ingredients)
    if ingredient_count <= 3:
        score += 0.1
    elif ingredient_count > 8:
        score -= 0.1

    # Factor in refinements - user refinements increase confidence
    if refinements:
        refinement_count = sum(len(r.updated_ingredients) + len(r.updated_assumptions)
                             for r in refinements if hasattr(r, 'updated_ingredients'))
        score += min(refinement_count * 0.05, 0.2)  # Cap bonus at 0.2

    # Clamp score between 0.1 and 1.0
    return max(0.1, min(1.0, score))


def get_recent_sessions(limit: int = 10) -> List[Dict]:
    """
    Get recent analysis sessions.

    Args:
        limit: Maximum number of sessions to return

    Returns:
        List of session dictionaries
    """
    if not os.path.exists(DB_PATH):
        return []

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row  # Enable dict-like access
    cur = con.cursor()

    cur.execute("""SELECT id, created_at, dish, portion_guess_g, confidence_score, tool_calls_count
                   FROM sessions
                   ORDER BY created_at DESC
                   LIMIT ?""", (limit,))

    sessions = [dict(row) for row in cur.fetchall()]
    con.close()

    return sessions


def get_session_details(session_id: int) -> Optional[Dict]:
    """
    Get detailed information about a specific session.

    Args:
        session_id: ID of the session

    Returns:
        Session details dictionary or None if not found
    """
    if not os.path.exists(DB_PATH):
        return None

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Get session data
    cur.execute("""SELECT * FROM sessions WHERE id = ?""", (session_id,))
    session = cur.fetchone()

    if not session:
        con.close()
        return None

    session_dict = dict(session)

    # Parse JSON fields
    if session_dict['ingredients_json']:
        session_dict['ingredients'] = json.loads(session_dict['ingredients_json'])

    if session_dict['refinements_json']:
        session_dict['refinements'] = json.loads(session_dict['refinements_json'])

    if session_dict['final_json']:
        try:
            session_dict['final_breakdown'] = json.loads(session_dict['final_json'])
        except:
            session_dict['final_breakdown'] = None

    # Get assumptions
    cur.execute("""SELECT assumption_key, assumption_value, confidence, created_at
                   FROM assumptions
                   WHERE session_id = ?
                   ORDER BY created_at""", (session_id,))
    session_dict['assumptions'] = [dict(row) for row in cur.fetchall()]

    # Get search queries
    cur.execute("""SELECT query, results_count, created_at
                   FROM search_queries
                   WHERE session_id = ?
                   ORDER BY created_at""", (session_id,))
    session_dict['search_queries'] = [dict(row) for row in cur.fetchall()]

    con.close()
    return session_dict


def get_db_stats() -> Dict:
    """
    Get database statistics.

    Returns:
        Dictionary with database statistics
    """
    if not os.path.exists(DB_PATH):
        return {"total_sessions": 0, "total_assumptions": 0, "total_searches": 0}

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Count sessions
    cur.execute("SELECT COUNT(*) FROM sessions")
    total_sessions = cur.fetchone()[0]

    # Count assumptions
    cur.execute("SELECT COUNT(*) FROM assumptions")
    total_assumptions = cur.fetchone()[0]

    # Count search queries
    cur.execute("SELECT COUNT(*) FROM search_queries")
    total_searches = cur.fetchone()[0]

    # Average confidence score
    cur.execute("SELECT AVG(confidence_score) FROM sessions")
    avg_confidence = cur.fetchone()[0] or 0.0

    # Most common dishes
    cur.execute("""SELECT dish, COUNT(*) as count
                   FROM sessions
                   GROUP BY dish
                   ORDER BY count DESC
                   LIMIT 5""")
    common_dishes = [{"dish": row[0], "count": row[1]} for row in cur.fetchall()]

    con.close()

    return {
        "total_sessions": total_sessions,
        "total_assumptions": total_assumptions,
        "total_searches": total_searches,
        "avg_confidence": avg_confidence,
        "common_dishes": common_dishes,
        "db_path": DB_PATH
    }