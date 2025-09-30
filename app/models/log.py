# from __future__ import annotations
# from .. import db
# from . import now_ny_naive
# from sqlalchemy.orm import relationship, foreign, backref
# from sqlalchemy import Index, UniqueConstraint, text


# class DataLog(db.Model):
#     __tablename__ = "data_logs"
#     __table_args__ = (
#         Index('idx_data_name_updatestamp', 'data_name'),
#         {"schema": "PLM"}
#     )

#     log_id = db.Column(db.Integer, primary_key=True)
#     data_name = db.Column(db.String(100), nullable=False)  # e.g., 'ItemLink', 'ItemLocations', 'ItemLocationsBR', 'PendingItems'
#     data_updatestamp = db.Column(db.DateTime(timezone=False), nullable=False)
#     last_refreshed = db.Column(db.DateTime(timezone=False), default=now_ny_naive, nullable=False)

#     def __repr__(self):
#         return f"<DataLog {self.data_name} last refreshed at {self.last_refreshed}>"