from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from business_prospector.application.ports import DuplicateMatch
from business_prospector.domain.exceptions import LeadNotFoundError
from business_prospector.domain.models import BusinessCandidate, Lead, WebsiteAssessment, utc_now
from business_prospector.domain.normalization import normalize_address, normalize_domain, normalize_phone, normalize_text
from business_prospector.domain.website_assessment import WebsiteAssessmentReport
from business_prospector.domain.first_website import FirstWebsiteMarketReport

SCHEMA_VERSION = 4

LEAD_COLUMNS = (
    "id", "external_place_id", "slug", "name", "normalized_name", "category", "city",
    "normalized_city", "address", "normalized_address", "maps_url", "rating", "review_count",
    "website_url", "normalized_domain", "phone", "normalized_phone", "whatsapp",
    "whatsapp_confirmed", "whatsapp_source", "email", "instagram", "website_issue_layout",
    "website_issue_mobile", "website_issue_cta", "website_issue_content",
    "website_issue_social_proof", "website_issue_platform", "website_issue_count",
    "qualification_reason", "score", "status", "source", "discovered_at", "last_checked_at",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_place_id TEXT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    category TEXT NOT NULL,
    city TEXT NOT NULL,
    normalized_city TEXT NOT NULL,
    address TEXT,
    normalized_address TEXT,
    maps_url TEXT,
    rating REAL NOT NULL CHECK (rating >= 0 AND rating <= 5),
    review_count INTEGER NOT NULL CHECK (review_count >= 0),
    website_url TEXT NOT NULL,
    normalized_domain TEXT,
    phone TEXT,
    normalized_phone TEXT,
    whatsapp TEXT,
    whatsapp_confirmed INTEGER NOT NULL DEFAULT 0 CHECK (whatsapp_confirmed IN (0, 1)),
    whatsapp_source TEXT NOT NULL DEFAULT 'unknown',
    email TEXT,
    instagram TEXT,
    website_issue_layout INTEGER NOT NULL DEFAULT 0,
    website_issue_mobile INTEGER NOT NULL DEFAULT 0,
    website_issue_cta INTEGER NOT NULL DEFAULT 0,
    website_issue_content INTEGER NOT NULL DEFAULT 0,
    website_issue_social_proof INTEGER NOT NULL DEFAULT 0,
    website_issue_platform INTEGER NOT NULL DEFAULT 0,
    website_issue_count INTEGER NOT NULL DEFAULT 0,
    qualification_reason TEXT NOT NULL DEFAULT '',
    score INTEGER NOT NULL DEFAULT 0 CHECK (score >= 0 AND score <= 100),
    status TEXT NOT NULL DEFAULT 'qualified' CHECK (status IN ('new','qualified','needs_review','contacted','proposal','closed','discarded','rejected')),
    source TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    last_checked_at TEXT NOT NULL,
    website_assessment_json TEXT,
    assessment_status TEXT,
    assessment_checked_at TEXT,
    batch_id TEXT,
    opportunity_type TEXT NOT NULL DEFAULT 'redesign' CHECK (opportunity_type IN ('redesign','first_website')),
    first_website_reason TEXT,
    market_research_json TEXT,
    market_research_status TEXT,
    market_research_checked_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_leads_external_place_id
    ON leads(external_place_id) WHERE external_place_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_leads_domain ON leads(normalized_domain);
CREATE INDEX IF NOT EXISTS ix_leads_phone ON leads(normalized_phone);
CREATE INDEX IF NOT EXISTS ix_leads_name_city ON leads(normalized_name, normalized_city);
CREATE INDEX IF NOT EXISTS ix_leads_address ON leads(normalized_address);
"""


class SQLiteLeadRepository:
    def __init__(self, database_path: Path, timeout: float = 10.0) -> None:
        self._path = database_path.resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=self._timeout)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version == 1:
                self._migrate_statuses(connection)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(leads)")}
            if "website_assessment_json" not in columns:
                self._migrate_structured_assessment(connection)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(leads)")}
            if "opportunity_type" not in columns:
                self._migrate_opportunity_type(connection)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @staticmethod
    def _migrate_statuses(connection: sqlite3.Connection) -> None:
        columns = ", ".join(LEAD_COLUMNS)
        connection.execute("ALTER TABLE leads RENAME TO leads_status_v1")
        connection.executescript(SCHEMA)
        connection.execute(
            f"INSERT INTO leads ({columns}) SELECT {columns} FROM leads_status_v1"  # noqa: S608
        )
        connection.execute("DROP TABLE leads_status_v1")
        connection.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_leads_external_place_id
                ON leads(external_place_id) WHERE external_place_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS ix_leads_domain ON leads(normalized_domain);
            CREATE INDEX IF NOT EXISTS ix_leads_phone ON leads(normalized_phone);
            CREATE INDEX IF NOT EXISTS ix_leads_name_city ON leads(normalized_name, normalized_city);
            CREATE INDEX IF NOT EXISTS ix_leads_address ON leads(normalized_address);
            """
        )

    @staticmethod
    def _migrate_structured_assessment(connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE leads ADD COLUMN website_assessment_json TEXT")
        connection.execute("ALTER TABLE leads ADD COLUMN assessment_status TEXT")
        connection.execute("ALTER TABLE leads ADD COLUMN assessment_checked_at TEXT")
        connection.execute("ALTER TABLE leads ADD COLUMN batch_id TEXT")

    @staticmethod
    def _migrate_opportunity_type(connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE leads ADD COLUMN opportunity_type TEXT NOT NULL DEFAULT 'redesign'")
        connection.execute("ALTER TABLE leads ADD COLUMN first_website_reason TEXT")
        connection.execute("ALTER TABLE leads ADD COLUMN market_research_json TEXT")
        connection.execute("ALTER TABLE leads ADD COLUMN market_research_status TEXT")
        connection.execute("ALTER TABLE leads ADD COLUMN market_research_checked_at TEXT")

    def save(self, lead: Lead) -> Lead:
        lead.validate()
        values = self._lead_values(lead)
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    f"INSERT INTO leads ({columns}) VALUES ({placeholders})",  # noqa: S608 - columns are internal constants
                    tuple(values.values()),
                )
                lead.id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"lead conflicts with an existing record: {exc}") from exc
        return lead

    def get(self, lead_id: int) -> Lead | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return self._row_to_lead(row) if row else None

    def list(self, limit: int = 100) -> list[Lead]:
        safe_limit = max(1, min(limit, 1000))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM leads ORDER BY score DESC, review_count DESC, name ASC LIMIT ?", (safe_limit,)
            ).fetchall()
        return [self._row_to_lead(row) for row in rows]

    def update(self, lead_id: int, changes: dict[str, object]) -> Lead:
        current = self.get(lead_id)
        if current is None:
            raise LeadNotFoundError(f"lead not found: {lead_id}")
        allowed = {
            "name", "category", "city", "address", "maps_url", "rating", "review_count", "website_url",
            "phone", "whatsapp", "whatsapp_confirmed", "whatsapp_source", "email", "instagram", "status",
            "external_place_id", "score",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported fields: {', '.join(sorted(unknown))}")
        for key, value in changes.items():
            setattr(current, key, value)
        current.last_checked_at = utc_now()
        current.validate()
        values = self._lead_values(current)
        assignments = ", ".join(f"{column} = ?" for column in values)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE leads SET {assignments} WHERE id = ?",  # noqa: S608 - columns are internal constants
                (*values.values(), lead_id),
            )
        return current

    def find_duplicate(self, candidate: BusinessCandidate | Lead) -> DuplicateMatch | None:
        external_id = candidate.external_place_id
        domain = normalize_domain(candidate.website_url)
        phone = normalize_phone(candidate.whatsapp or candidate.phone)
        name = normalize_text(candidate.name)
        city = normalize_text(candidate.city)
        address = normalize_address(candidate.address)
        checks = (
            ("external_place_id", external_id, "exact"),
            ("normalized_domain", domain, "likely"),
            ("normalized_phone", phone, "likely"),
        )
        with self._connect() as connection:
            for column, value, confidence in checks:
                if value:
                    row = connection.execute(f"SELECT id FROM leads WHERE {column} = ? LIMIT 1", (value,)).fetchone()
                    if row:
                        return DuplicateMatch(int(row["id"]), column, confidence)
            row = connection.execute(
                "SELECT id FROM leads WHERE normalized_name = ? AND normalized_city = ? LIMIT 1", (name, city)
            ).fetchone()
            if row:
                return DuplicateMatch(int(row["id"]), "normalized_name_city", "possible")
            if address:
                row = connection.execute(
                    "SELECT id FROM leads WHERE normalized_address = ? LIMIT 1", (address,)
                ).fetchone()
                if row:
                    return DuplicateMatch(int(row["id"]), "normalized_address", "possible")
        return None

    @staticmethod
    def _lead_values(lead: Lead) -> dict[str, Any]:
        a = lead.assessment
        structured = None
        if lead.website_assessment is not None:
            report = WebsiteAssessmentReport.from_dict(lead.website_assessment)
            if lead.assessment_status != report.status:
                raise ValueError("assessment_status must match the structured report")
            structured = report.to_dict()
        market_research = None
        if lead.market_research is not None:
            research = FirstWebsiteMarketReport.from_dict(lead.market_research)
            if lead.market_research_status != research.status:
                raise ValueError("market_research_status must match the structured report")
            market_research = research.to_dict()
        return {
            "external_place_id": lead.external_place_id,
            "slug": lead.slug,
            "name": lead.name,
            "normalized_name": lead.normalized_name,
            "category": lead.category,
            "city": lead.city,
            "normalized_city": lead.normalized_city,
            "address": lead.address,
            "normalized_address": lead.normalized_address,
            "maps_url": lead.maps_url,
            "rating": lead.rating,
            "review_count": lead.review_count,
            "website_url": lead.website_url,
            "normalized_domain": lead.normalized_domain,
            "phone": lead.phone,
            "normalized_phone": lead.normalized_phone,
            "whatsapp": lead.whatsapp,
            "whatsapp_confirmed": int(lead.whatsapp_confirmed),
            "whatsapp_source": lead.whatsapp_source,
            "email": lead.email,
            "instagram": lead.instagram,
            "website_issue_layout": int(a.layout),
            "website_issue_mobile": int(a.mobile),
            "website_issue_cta": int(a.cta),
            "website_issue_content": int(a.content),
            "website_issue_social_proof": int(a.social_proof),
            "website_issue_platform": int(a.platform),
            "website_issue_count": a.issue_count,
            "qualification_reason": a.reason,
            "score": lead.score,
            "status": lead.status,
            "source": lead.source,
            "discovered_at": lead.discovered_at,
            "last_checked_at": lead.last_checked_at,
            "website_assessment_json": (
                json.dumps(structured, ensure_ascii=False, separators=(",", ":"))
                if structured is not None else None
            ),
            "assessment_status": lead.assessment_status,
            "assessment_checked_at": lead.assessment_checked_at,
            "batch_id": lead.batch_id,
            "opportunity_type": lead.opportunity_type,
            "first_website_reason": lead.first_website_reason,
            "market_research_json": (
                json.dumps(market_research, ensure_ascii=False, separators=(",", ":"))
                if market_research is not None else None
            ),
            "market_research_status": lead.market_research_status,
            "market_research_checked_at": lead.market_research_checked_at,
        }

    @staticmethod
    def _row_to_lead(row: sqlite3.Row) -> Lead:
        assessment = WebsiteAssessment(
            layout=bool(row["website_issue_layout"]),
            mobile=bool(row["website_issue_mobile"]),
            cta=bool(row["website_issue_cta"]),
            content=bool(row["website_issue_content"]),
            social_proof=bool(row["website_issue_social_proof"]),
            platform=bool(row["website_issue_platform"]),
            reason=row["qualification_reason"],
        )
        structured: dict[str, Any] | None = None
        raw_structured = row["website_assessment_json"]
        if raw_structured:
            payload = json.loads(raw_structured)
            structured = WebsiteAssessmentReport.from_dict(payload).to_dict()
        market_research: dict[str, Any] | None = None
        raw_market = row["market_research_json"]
        if raw_market:
            market_research = FirstWebsiteMarketReport.from_dict(json.loads(raw_market)).to_dict()
        return Lead(
            id=row["id"], external_place_id=row["external_place_id"], slug=row["slug"], name=row["name"],
            category=row["category"], city=row["city"], address=row["address"], maps_url=row["maps_url"],
            rating=row["rating"], review_count=row["review_count"], website_url=row["website_url"],
            phone=row["phone"], whatsapp=row["whatsapp"], whatsapp_confirmed=bool(row["whatsapp_confirmed"]),
            whatsapp_source=row["whatsapp_source"], email=row["email"], instagram=row["instagram"],
            assessment=assessment, score=row["score"], status=row["status"], source=row["source"],
            discovered_at=row["discovered_at"], last_checked_at=row["last_checked_at"],
            website_assessment=structured, assessment_status=row["assessment_status"],
            assessment_checked_at=row["assessment_checked_at"], batch_id=row["batch_id"],
            opportunity_type=row["opportunity_type"], first_website_reason=row["first_website_reason"],
            market_research=market_research, market_research_status=row["market_research_status"],
            market_research_checked_at=row["market_research_checked_at"],
        )
