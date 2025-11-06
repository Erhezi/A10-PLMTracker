from __future__ import annotations
from .. import db
from . import now_ny_naive
from sqlalchemy.orm import relationship, foreign, backref
from sqlalchemy import Index, UniqueConstraint, text


class BurnRateRefreshJob(db.Model):
	__tablename__ = "burn_rate_refresh_job"
	__table_args__ = (
		Index("IX_BurnRateRefreshJob_ItemLink", "item_link_id"),
		{"schema": "PLM"},
	)

	id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
	item_link_id = db.Column(
		db.BigInteger,
		db.ForeignKey("PLM.ItemLink.PKID", ondelete="CASCADE"),
		nullable=False,
	)
	status = db.Column(db.String(20), nullable=False, default="PENDING")
	message = db.Column(db.String(500), nullable=True)
	created_at = db.Column(db.DateTime(timezone=False), nullable=False, default=now_ny_naive)
	started_at = db.Column(db.DateTime(timezone=False), nullable=True)
	finished_at = db.Column(db.DateTime(timezone=False), nullable=True)

	item_link = relationship(
		"ItemLink",
		backref=backref("burn_rate_jobs", cascade="all, delete-orphan"),
	)

	def mark_running(self) -> None:
		timestamp = now_ny_naive()
		self.status = "RUNNING"
		self.started_at = timestamp
		# keep existing finished_at until job completes

	def mark_success(self, *, message: str | None = None) -> None:
		self.status = "SUCCESS"
		self.finished_at = now_ny_naive()
		if message:
			self.message = message

	def mark_failure(self, message: str) -> None:
		self.status = "FAILED"
		self.finished_at = now_ny_naive()
		self.message = (message or "")[:500]


class ProcessLog(db.Model):
	"""Mapping to PLM.process_log table.

	Mirrors the SQL Server table definition provided by the user:
	- schema: PLM
	- identity primary key pkid (BIGINT)
	- process_name (SYSNAME -> VARCHAR(128) in SQLAlchemy mapping)
	- exec_start, exec_end (DATETIME2(3)) stored in the server's local/system time (SYSDATETIME())
	- status (VARCHAR(16)) with default 'Unknown'
	- err_msg (NVARCHAR(4000))
	- duration_ms computed as DATEDIFF_BIG(ms, exec_start, exec_end) when end is present
	"""

	__tablename__ = "process_log"
	__table_args__ = (
		Index('IX_PLM_ProcessLog_Time', 'exec_start'),
		Index('IX_PLM_ProcessLog_Status', 'status', 'exec_start'),
		{"schema": "PLM"},
	)

	pkid = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
	process_name = db.Column(db.String(128), nullable=False)
	exec_start = db.Column(db.DateTime(timezone=False), nullable=False)
	exec_end = db.Column(db.DateTime(timezone=False), nullable=True)
	status = db.Column(db.String(16), nullable=False, server_default=text("'Unknown'"))
	err_msg = db.Column(db.Unicode(4000), nullable=True)

	# Computed column for duration in milliseconds. SQLAlchemy doesn't have a
	# direct cross-database computed column helper for SQL Server DATEDIFF_BIG;
	# we map it as a regular column and provide a read-only expression using
	# a hybrid property when exec_end_utc is present. If you prefer the
	# database to maintain the persisted computed column, create it in the DB
	# and remove this property.
	@property
	def duration_ms(self) -> int | None:
		if self.exec_end is None or self.exec_start is None:
			return None
		# compute in Python as an integer number of milliseconds
		delta = self.exec_end - self.exec_start
		return int(delta.total_seconds() * 1000)

	def __repr__(self):  # pragma: no cover - debug aid
		return (
			f"<ProcessLog pkid={self.pkid} process={self.process_name!r}"
			f" start={self.exec_start} end={self.exec_end} status={self.status}>"
		)

	@classmethod
	def get_latest_success_timestamp(cls, session):
		"""Get the latest exec_end timestamp where status is SUCCESS.
		
		Returns:
			datetime or None: The latest successful execution end time, or None if not found.
		"""
		from sqlalchemy import select, func, or_
		# Try both 'Success' and 'SUCCESS' to be case-insensitive
		result = session.execute(
			select(func.max(cls.exec_end))
			.where(or_(cls.status == 'Success', cls.status == 'SUCCESS'))
			.where(cls.exec_end.isnot(None))
		).scalar()
		print(f"[DEBUG ProcessLog] Query result: {result}")
		return result



