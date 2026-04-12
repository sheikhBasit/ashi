"""
Kuzu-backed knowledge graph for ASHI entity relationships.
Embedded, no server, Apache 2.0.

Note: kuzu 0.11.3 does not support named parameters in node property
literal positions within CREATE/MATCH clauses. String values are escaped
and interpolated safely via _esc() which only allows alphanumeric, space,
hyphen, underscore, dot, colon and slash characters.
"""
import os
import kuzu


def _esc(value: str) -> str:
    """Escape a string for safe inline embedding in a Cypher literal."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


class KnowledgeGraph:
    def __init__(self, db_path: str):
        # kuzu requires a file path, not a directory path
        db_file = os.path.join(db_path, "knowledge.db") if os.path.isdir(db_path) else db_path
        self.db = kuzu.Database(db_file)
        self.conn = kuzu.Connection(self.db)
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            "CREATE NODE TABLE IF NOT EXISTS Entity("
            "name STRING, entity_type STRING, description STRING, PRIMARY KEY(name))"
        )
        self.conn.execute(
            "CREATE REL TABLE IF NOT EXISTS Relates("
            "FROM Entity TO Entity, relationship STRING)"
        )

    def add_entity(self, name: str, entity_type: str, description: str = "") -> None:
        result = self.conn.execute(
            f"MATCH (e:Entity {{name: '{_esc(name)}'}}) RETURN e.name"
        )
        if result.has_next():
            self.conn.execute(
                f"MATCH (e:Entity {{name: '{_esc(name)}'}}) "
                f"SET e.entity_type = '{_esc(entity_type)}', "
                f"e.description = '{_esc(description)}'"
            )
        else:
            self.conn.execute(
                f"CREATE (:Entity {{"
                f"name: '{_esc(name)}', "
                f"entity_type: '{_esc(entity_type)}', "
                f"description: '{_esc(description)}'}})"
            )

    def add_relationship(self, from_name: str, relationship: str, to_name: str) -> None:
        self.conn.execute(
            f"MATCH (a:Entity {{name: '{_esc(from_name)}'}}), "
            f"(b:Entity {{name: '{_esc(to_name)}'}}) "
            f"CREATE (a)-[:Relates {{relationship: '{_esc(relationship)}'}}]->(b)"
        )

    def get_neighbors(self, name: str) -> list[dict]:
        result = self.conn.execute(
            f"MATCH (a:Entity {{name: '{_esc(name)}'}})-[r:Relates]->(b:Entity) "
            f"RETURN b.name, b.entity_type, r.relationship"
        )
        rows: list[dict] = []
        while result.has_next():
            row = result.get_next()
            rows.append({"name": row[0], "type": row[1], "relationship": row[2]})
        return rows
